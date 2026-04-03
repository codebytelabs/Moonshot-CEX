"""
AnalyzerAgent — Multi-timeframe technical analysis.
Takes watcher candidates and performs deep TA across 5m/15m/1h/4h.
Outputs setup type, ta_score, entry_zone, and ML features.
"""
import time
from typing import Optional
from loguru import logger
import numpy as np

from .exchange_ccxt import ExchangeConnector
from .redis_client import RedisClient
from .watcher import _compute_rsi, _compute_macd_hist, _compute_obv, _ema
from .metrics import signals_generated


SETUP_TYPES = [
    "breakout",
    "momentum",
    "pullback",
    "mean_reversion",
    "consolidation_breakout",
    "neutral",
]


class AnalyzerAgent:
    """Multi-timeframe TA agent producing scored setups with entry zones."""

    def __init__(
        self,
        exchange: ExchangeConnector,
        redis: Optional[RedisClient] = None,
        timeframes: list[str] = None,
        min_score: float = 30.0,
        top_n: int = 5,
    ):
        self.exchange = exchange
        self.redis = redis
        self.timeframes = timeframes or ["5m", "15m", "1h", "4h"]
        self.min_score = min_score
        self.top_n = top_n

    async def analyze(self, candidates: list[dict], regime: str = "sideways") -> list[dict]:
        """
        Run multi-timeframe TA on top watcher candidates.
        Returns list of setups sorted by ta_score descending.
        """
        t0 = time.monotonic()
        results = []

        # Regime boost removed — RSI/EMA/MACD hard gates handle quality control.
        # Small bear-only penalty (3 pts) prevents worst setups without freezing everything.
        # Sideways boost removed: individual tokens can momentum-run even in flat markets.
        regime_boost = {"bull": 0, "sideways": 0, "bear": 3, "choppy": 5}.get(regime, 0)
        effective_min_score = self.min_score + regime_boost

        for candidate in candidates:
            setup = await self._analyze_symbol(candidate, regime=regime)
            if setup and setup["ta_score"] >= effective_min_score:
                results.append(setup)

        results.sort(key=lambda x: x["ta_score"], reverse=True)
        top = results[: self.top_n]

        elapsed = time.monotonic() - t0
        signals_generated.labels(agent="analyzer").inc(len(top))
        logger.info(f"[Analyzer] Analyzed {len(candidates)} candidates → {len(top)} setups [{elapsed:.1f}s]")
        return top

    async def _analyze_symbol(self, candidate: dict, regime: str = "sideways") -> Optional[dict]:
        symbol = candidate["symbol"]
        price = candidate.get("price", 0.0)
        if price <= 0:
            logger.debug(f"[Analyzer] {symbol} skip: price={price}")
            return None

        tf_data = {}
        tf_counts = {}
        for tf in self.timeframes:
            candles = await self._fetch_ohlcv_cached(symbol, tf, 200)
            count = len(candles) if candles else 0
            tf_counts[tf] = count
            if candles and count >= 50:
                tf_data[tf] = np.array(candles, dtype=float)

        if not tf_data or "5m" not in tf_data:
            logger.info(f"[Analyzer] {symbol} skip: insufficient OHLCV {tf_counts}")
            return None

        ta_scores = {}
        for tf, data in tf_data.items():
            ta_scores[tf] = self._compute_tf_score(data)

        # Momentum trading: 15m + 1h dominate — they catch real-time moves.
        # 4h defines trend direction but lags too much for entry timing.
        # 5m captures immediate momentum (higher than before — momentum is NOW).
        weights = {"5m": 0.15, "15m": 0.30, "1h": 0.35, "4h": 0.20}
        total_weight = sum(weights[tf] for tf in ta_scores)
        ta_score = sum(ta_scores[tf] * weights[tf] for tf in ta_scores) / total_weight

        # ATR from 1h for stop sizing — 5m ATR is too noisy and places stops
        # within normal market microstructure, causing immediate stop-outs.
        # 1h ATR captures meaningful volatility over a tradeable timeframe.
        data_5m = tf_data["5m"]
        atr_src = tf_data.get("1h", data_5m)
        atr = _compute_atr(atr_src[:, 2], atr_src[:, 3], atr_src[:, 4], 14)

        # Support / resistance from 1h or 15m
        sr_tf = tf_data.get("1h", tf_data.get("15m", data_5m))
        support, resistance = _compute_support_resistance(sr_tf[:, 2], sr_tf[:, 3], sr_tf[:, 4])

        # ── 4h EMA50 trend gate (loose): only block deeply falling tokens ──────
        # 10% tolerance — only rejects tokens crashing hard in a 4h downtrend.
        # Individual momentum breakouts trade fine even when below 4h EMA50.
        direction = candidate.get("direction", "long")
        if direction == "long" and "4h" in tf_data:
            closes_4h = tf_data["4h"][:, 4]
            if len(closes_4h) >= 50:
                ema50_4h = _ema(closes_4h, 50)
                if closes_4h[-1] < ema50_4h * 0.90:
                    logger.debug(
                        f"[Analyzer] {symbol} filtered: price {closes_4h[-1]:.6f} "
                        f"< EMA50 {ema50_4h:.6f} * 0.90 (deeply below trend)"
                    )
                    return None

        # ── ANTI-CHASE: hard pullback-from-high gate ──────────────────────────
        # If price has already peaked and pulled back >3% from recent high,
        # the pump is OVER — do NOT enter regardless of other signals.
        # This is the #1 fix for DUSDT/PROMPTUSDT "bought the top" entries.
        _closes_5m = data_5m[:, 4]
        _highs_5m = data_5m[:, 2]
        if direction == "long" and len(_highs_5m) >= 12:
            _recent_high = float(np.max(_highs_5m[-12:]))
            _current = float(_closes_5m[-1])
            if _recent_high > 0:
                _pullback_pct = (_recent_high - _current) / _recent_high * 100.0
                if _pullback_pct >= 3.0:
                    logger.info(
                        f"[Analyzer] {symbol} BLOCKED: price {_current:.6f} is {_pullback_pct:.1f}% "
                        f"below 1h high {_recent_high:.6f} — pump already topped"
                    )
                    return None

        # ── Momentum fast-track: >2% 1h return bypasses EMA/MACD gates ────────
        # When price is ACTUALLY pumping NOW, lagging indicators haven't confirmed.
        # But fast-track must verify the move is STILL ACTIVE — not a completed pump.
        # Exhaustion checks prevent entering dying pumps (DUSDT/PROMPTUSDT pattern).
        _fast_track = False
        _return_1h = 0.0
        if len(_closes_5m) >= 13:
            _return_1h = (_closes_5m[-1] - _closes_5m[-13]) / _closes_5m[-13] * 100.0
            if _return_1h >= 2.0:
                # Exhaustion check 1: price must be within 2.5% of recent 1h high
                # If it's already pulled back more, the move is dying
                _ft_high = float(np.max(_highs_5m[-12:])) if len(_highs_5m) >= 12 else _closes_5m[-1]
                _ft_pullback = (_ft_high - _closes_5m[-1]) / _ft_high * 100.0 if _ft_high > 0 else 0
                _ft_near_high = _ft_pullback < 2.5

                # Exhaustion check 2: candle quality
                # Near high (<1%): 1/3 green is enough (move is fresh, one doji is OK)
                # Further out (1-2.5%): need 2/3 green (prove buyers are still here)
                _ft_green_count = 0
                if len(_closes_5m) >= 4:
                    _ft_green_count = sum(1 for i in range(-3, 0) if _closes_5m[i] > _closes_5m[i - 1])
                _ft_candles_ok = _ft_green_count >= 2 or (_ft_pullback < 1.0 and _ft_green_count >= 1)

                # Exhaustion check 3: 5m RSI must be in momentum zone (>45)
                # Pullback + candle checks are the REAL dying-pump protection.
                # RSI cap is tiered by strength: strong pumps (≥5%) tolerate RSI up to 96,
                # moderate (2-5%) up to 92. CYS +15.2%/RSI=94 was blocked at 82 — lost profits.
                # RSI <45 = momentum has already faded
                _ft_rsi = _compute_rsi(_closes_5m, 14) if len(_closes_5m) >= 15 else 50.0
                _ft_rsi_cap = 96.0 if _return_1h >= 5.0 else 92.0
                _ft_rsi_ok = 45 < _ft_rsi < _ft_rsi_cap

                if _ft_near_high and _ft_candles_ok and _ft_rsi_ok:
                    _fast_track = True
                    logger.info(
                        f"[Analyzer] {symbol} FAST-TRACK: 1h return +{_return_1h:.1f}% "
                        f"pullback={_ft_pullback:.1f}% green={_ft_green_count}/3 RSI={_ft_rsi:.0f} — approved"
                    )
                else:
                    logger.info(
                        f"[Analyzer] {symbol} FAST-TRACK DENIED: 1h return +{_return_1h:.1f}% "
                        f"but pullback={_ft_pullback:.1f}% green={_ft_green_count}/3 RSI={_ft_rsi:.0f} — "
                        f"pump exhausting, applying normal gates"
                    )

        # ── EMA alignment: 1h OR 15m EMA9 > EMA21 ────────────────────────────
        # Momentum tokens breaking out on 15m may not yet show 1h EMA9>EMA21 (lagging).
        # Accept either timeframe — catches early breakouts before 1h confirms.
        # SKIPPED if fast-track (price already confirmed momentum).
        if direction == "long" and not _fast_track:
            _ema_ok = False
            if "1h" in tf_data:
                _c1h = tf_data["1h"][:, 4]
                if len(_c1h) >= 21 and _ema(_c1h, 9) > _ema(_c1h, 21):
                    _ema_ok = True
            if not _ema_ok and "15m" in tf_data:
                _c15m = tf_data["15m"][:, 4]
                if len(_c15m) >= 21 and _ema(_c15m, 9) > _ema(_c15m, 21) * 1.001:
                    _ema_ok = True
            if not _ema_ok:
                logger.debug(f"[Analyzer] {symbol} filtered: neither 1h nor 15m EMA9>EMA21")
                return None

        # ── RSI gate: 40-82, block overbought entries ─────────────────────────
        # RSI 70-82 = strong momentum (still OK to enter).
        # RSI >82 = overbought — entering here is chasing completed moves.
        # 78 cap was too aggressive — blocked CHR(80), ALT(79), JCT(78) which
        # were valid momentum entries with 0% pullback and 2/3 green candles.
        # Dying-pump protection comes from pullback gate + candle check, not RSI.
        if direction == "long" and "1h" in tf_data:
            _c1h_rsi = tf_data["1h"][:, 4]
            if len(_c1h_rsi) >= 14:
                rsi_1h = _compute_rsi(_c1h_rsi, 14)
                _rsi_cap = 88.0
                if rsi_1h > _rsi_cap:
                    logger.info(f"[Analyzer] {symbol} filtered: 1h RSI {rsi_1h:.1f} > {_rsi_cap:.0f} (overbought)")
                    return None
                if rsi_1h < 40 and not _fast_track:
                    logger.debug(f"[Analyzer] {symbol} filtered: 1h RSI {rsi_1h:.1f} < 40 (no momentum)")
                    return None
                # Check for declining RSI from overbought: distribution signal
                if len(_c1h_rsi) >= 16 and not _fast_track:
                    _rsi_prev = _compute_rsi(_c1h_rsi[:-2], 14)
                    if _rsi_prev > 75 and rsi_1h < _rsi_prev - 3:
                        logger.info(
                            f"[Analyzer] {symbol} filtered: 1h RSI declining from overbought "
                            f"({_rsi_prev:.1f} → {rsi_1h:.1f}) — distribution"
                        )
                        return None

        # ── MACD confirmation: hist > 0 OR rising ─────────────────────────────
        # hist > 0 = confirmed momentum. hist rising (crossing from below) = momentum STARTING.
        # Old gate (hist > 0 only) fired too late — move was 50% done by confirmation.
        # SKIPPED if fast-track (price already confirmed momentum).
        if direction == "long" and "1h" in tf_data and not _fast_track:
            _c1h_macd = tf_data["1h"][:, 4]
            if len(_c1h_macd) >= 36:
                hist_now = _compute_macd_hist(_c1h_macd, 12, 26, 9)
                hist_prev = _compute_macd_hist(_c1h_macd[:-1], 12, 26, 9)
                if hist_now <= 0 and hist_now <= hist_prev:
                    logger.debug(
                        f"[Analyzer] {symbol} filtered: 1h MACD {hist_now:.6f} ≤0 and not rising"
                    )
                    return None

        # Setup classification
        setup_type = self._classify_setup(tf_data, ta_scores)
        # Tokens that cleared all hard filter gates ARE showing momentum signals.
        # 'neutral' just means score patterns don't fit a clean category — trade it
        # as momentum. Position sizing (kelly × ta_score) auto-scales weak signals smaller.
        if setup_type == "neutral":
            setup_type = "momentum"

        # Entry zone
        entry_zone = self._compute_entry_zone(price, atr, support, resistance, setup_type)
        if entry_zone is None:
            return None

        # ML features
        features = self._extract_ml_features(tf_data, candidate)

        return {
            "symbol": symbol,
            "setup_type": setup_type,
            "ta_score": round(ta_score, 2),
            "ta_scores_by_tf": {k: round(v, 2) for k, v in ta_scores.items()},
            "entry_zone": entry_zone,
            "atr": round(atr, 8),
            "support": round(support, 8),
            "resistance": round(resistance, 8),
            "price": price,
            "watcher_score": candidate.get("score", 0.0),
            "rsi_5m": candidate.get("rsi", 50.0),
            "vol_usd": candidate.get("vol_usd", 0.0),
            "vol_ratio": candidate.get("vol_ratio", 1.0),
            "pct_change_24h": candidate.get("pct_change_24h", 0.0),
            "features": features,
            "timestamp": int(time.time()),
        }

    def _compute_tf_score(self, data: np.ndarray) -> float:
        closes = data[:, 4]
        volumes = data[:, 5]
        score = 0.0

        # RSI
        rsi = _compute_rsi(closes, 14)
        if 45 <= rsi <= 70:
            score += 20.0 * (1.0 - abs(rsi - 57.5) / 12.5)
        elif rsi < 45:
            score += max(0.0, 20.0 * (rsi - 30) / 15.0)
        else:
            score += max(0.0, 20.0 * (80 - rsi) / 10.0)

        # MACD
        macd_hist = _compute_macd_hist(closes, 12, 26, 9)
        score += min(20.0, max(0.0, macd_hist * 100.0)) if macd_hist > 0 else 0.0

        # EMA alignment
        ema9 = _ema(closes, 9)
        ema21 = _ema(closes, 21)
        ema50 = _ema(closes, 50) if len(closes) >= 50 else None
        if ema50 is not None and ema9 > ema21 > ema50:
            score += 20.0
        elif ema9 > ema21:
            score += 10.0

        # Volume spike
        avg_vol = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes))
        vol_ratio = float(volumes[-1]) / avg_vol if avg_vol > 0 else 1.0
        score += min(20.0, max(0.0, (vol_ratio - 1.0) * 10.0))

        # OBV trend
        obv = _compute_obv(closes, volumes)
        if len(obv) >= 10:
            obv_slope = (obv[-1] - obv[-10]) / (abs(obv[-10]) + 1e-9)
            score += min(20.0, max(0.0, obv_slope * 20.0))

        return min(100.0, score)

    def _classify_setup(self, tf_data: dict, ta_scores: dict) -> str:
        score_5m = ta_scores.get("5m", 0.0)
        score_1h = ta_scores.get("1h", 0.0)
        score_4h = ta_scores.get("4h", 0.0)

        data_5m = tf_data.get("5m")
        if data_5m is None:
            return "neutral"

        closes = data_5m[:, 4]
        volumes = data_5m[:, 5]
        rsi = _compute_rsi(closes, 14)
        avg_vol = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else 1.0
        vol_spike = float(volumes[-1]) / avg_vol if avg_vol > 0 else 1.0

        # Bollinger Band width for consolidation
        if len(closes) >= 20:
            bb_mean = float(np.mean(closes[-20:]))
            bb_std = float(np.std(closes[-20:]))
            bb_width = (2 * bb_std) / bb_mean if bb_mean > 0 else 0.1
        else:
            bb_width = 0.05

        # ── Setup classification — CALIBRATED for actual market conditions ────
        # Old thresholds (score_4h>=60, score_1h>=55) were only met in strong bull
        # runs, causing 100% neutral classification in sideways/bear markets.
        # New thresholds: achievable with moderate signals across timeframes.

        # BREAKOUT: strong 4h + 1h alignment + volume expansion
        if score_4h >= 50 and score_1h >= 40 and rsi >= 50 and vol_spike >= 1.3:
            return "breakout"

        # MOMENTUM: 4h trend established OR 1h+5m confluence OR relative-strength intra-day surge.
        # RSI bounds match the 40-92 filter gate — tokens at RSI 72-90 are peak momentum, not top.
        elif (
            (score_4h >= 40 and score_1h >= 35 and 42 <= rsi <= 92)
            or (score_4h >= 35 and score_5m >= 30 and 48 <= rsi <= 92)
            or (score_5m >= 42 and score_1h >= 30 and 50 <= rsi <= 92)
        ):
            return "momentum"

        # PULLBACK: strong 4h trend but RSI dipped — potential re-entry
        elif score_4h >= 45 and rsi < 48:
            return "pullback"

        # MEAN REVERSION: oversold + tight range
        elif rsi < 35 and bb_width < 0.04:
            return "mean_reversion"

        # CONSOLIDATION BREAKOUT: volume surge out of tight range
        elif bb_width < 0.035 and vol_spike >= 1.8:
            return "consolidation_breakout"

        else:
            return "neutral"

    def _compute_entry_zone(
        self,
        price: float,
        atr: float,
        support: float,
        resistance: float,
        setup_type: str,
    ) -> Optional[dict]:
        if atr <= 0:
            return None

        if setup_type in ("breakout", "consolidation_breakout"):
            entry = price
            stop_loss = price - 1.5 * atr
            take_profit_1 = price + 2.0 * (price - stop_loss)
            take_profit_2 = price + 5.0 * (price - stop_loss)
        elif setup_type == "momentum":
            entry = price
            stop_loss = price - 1.8 * atr
            take_profit_1 = price + 2.0 * (price - stop_loss)
            take_profit_2 = price + 4.0 * (price - stop_loss)
        elif setup_type == "pullback":
            entry = price
            stop_loss = max(support - 0.5 * atr, price - 2.0 * atr)
            take_profit_1 = price + 2.0 * (price - stop_loss)
            take_profit_2 = price + 5.0 * (price - stop_loss)
        elif setup_type == "mean_reversion":
            entry = price
            stop_loss = price - 1.2 * atr
            take_profit_1 = price + 1.5 * (price - stop_loss)
            take_profit_2 = price + 3.0 * (price - stop_loss)
        else:
            entry = price
            stop_loss = price - 2.0 * atr
            take_profit_1 = price + 2.0 * (price - stop_loss)
            take_profit_2 = price + 4.0 * (price - stop_loss)

        if stop_loss >= entry:
            return None

        risk_per_unit = entry - stop_loss

        # ── Enforce minimum 2% stop distance ──────────────────────────────────
        # ATR-based stops can be <1% on low-volatility tokens — these get hit
        # on normal market noise, creating constant stop-outs. Minimum = 2%.
        min_risk = entry * 0.02
        if risk_per_unit < min_risk:
            risk_per_unit = min_risk
            stop_loss = entry - risk_per_unit
            take_profit_1 = entry + 2.0 * risk_per_unit
            take_profit_2 = entry + 4.0 * risk_per_unit
        # ── Enforce maximum 6% stop distance (config safety net) ─────────
        max_risk = entry * 0.06
        if risk_per_unit > max_risk:
            risk_per_unit = max_risk
            stop_loss = entry - risk_per_unit
            take_profit_1 = entry + 2.0 * risk_per_unit
            take_profit_2 = entry + 4.0 * risk_per_unit

        rr_ratio = (take_profit_1 - entry) / risk_per_unit if risk_per_unit > 0 else 0.0

        # Reject setups where R:R is below 1.8 — not worth the risk
        if rr_ratio < 1.8:
            return None

        return {
            "entry": round(entry, 8),
            "stop_loss": round(stop_loss, 8),
            "take_profit_1": round(take_profit_1, 8),
            "take_profit_2": round(take_profit_2, 8),
            "risk_per_unit": round(risk_per_unit, 8),
            "rr_ratio": round(rr_ratio, 2),
        }

    def _extract_ml_features(self, tf_data: dict, candidate: dict) -> dict:
        features = {
            "rsi_5m": candidate.get("rsi", 50.0),
            "vol_ratio_5m": candidate.get("vol_ratio", 1.0),
            "pct_change_24h": candidate.get("pct_change_24h", 0.0),
            "ema_aligned": float(candidate.get("ema_aligned", False)),
        }
        for tf, data in tf_data.items():
            closes = data[:, 4]
            features[f"rsi_{tf}"] = round(_compute_rsi(closes, 14), 1)
            features[f"macd_{tf}"] = round(_compute_macd_hist(closes, 12, 26, 9), 6)
        return features

    async def _fetch_ohlcv_cached(self, symbol: str, timeframe: str, limit: int) -> Optional[list]:
        if self.redis:
            cached = await self.redis.get_ohlcv(symbol, timeframe)
            if cached:
                return cached
        try:
            candles = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if self.redis and candles:
                await self.redis.cache_ohlcv(symbol, timeframe, candles, ttl=240)
            return candles
        except Exception as e:
            logger.debug(f"[Analyzer] OHLCV fetch failed {symbol}/{timeframe}: {e}")
            return None


# ── Indicator helpers ────────────────────────────────────────────────────────

def _compute_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < 2:
        return 0.0
    tr_list = []
    for i in range(1, len(closes)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr_list.append(max(hl, hc, lc))
    tr = np.array(tr_list)
    if len(tr) < period:
        return float(np.mean(tr))
    return float(np.mean(tr[-period:]))


def _compute_support_resistance(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, lookback: int = 50) -> tuple:
    window = min(lookback, len(closes))
    recent_lows = lows[-window:]
    recent_highs = highs[-window:]
    support = float(np.min(recent_lows)) if len(recent_lows) > 0 else float(closes[-1]) * 0.95
    resistance = float(np.max(recent_highs)) if len(recent_highs) > 0 else float(closes[-1]) * 1.05
    return support, resistance
