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

    async def analyze(self, candidates: list[dict]) -> list[dict]:
        """
        Run multi-timeframe TA on top watcher candidates.
        Returns list of setups sorted by ta_score descending.
        """
        t0 = time.monotonic()
        results = []

        for candidate in candidates[: self.top_n * 2]:
            setup = await self._analyze_symbol(candidate)
            if setup and setup["ta_score"] >= self.min_score:
                results.append(setup)

        results.sort(key=lambda x: x["ta_score"], reverse=True)
        top = results[: self.top_n]

        elapsed = time.monotonic() - t0
        signals_generated.labels(agent="analyzer").inc(len(top))
        logger.info(f"[Analyzer] Analyzed {len(candidates)} candidates → {len(top)} setups [{elapsed:.1f}s]")
        return top

    async def _analyze_symbol(self, candidate: dict) -> Optional[dict]:
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

        weights = {"5m": 0.20, "15m": 0.30, "1h": 0.30, "4h": 0.20}
        total_weight = sum(weights[tf] for tf in ta_scores)
        ta_score = sum(ta_scores[tf] * weights[tf] for tf in ta_scores) / total_weight

        # ATR from 5m for risk sizing
        data_5m = tf_data["5m"]
        atr = _compute_atr(data_5m[:, 2], data_5m[:, 3], data_5m[:, 4], 14)

        # Support / resistance from 1h or 15m
        sr_tf = tf_data.get("1h", tf_data.get("15m", data_5m))
        support, resistance = _compute_support_resistance(sr_tf[:, 2], sr_tf[:, 3], sr_tf[:, 4])

        # Setup classification
        setup_type = self._classify_setup(tf_data, ta_scores)

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

        if score_4h >= 60 and score_1h >= 55 and rsi >= 55 and vol_spike >= 1.5:
            return "breakout"
        elif score_1h >= 50 and score_4h >= 45 and 50 <= rsi <= 70:
            return "momentum"
        elif score_4h >= 55 and rsi < 45:
            return "pullback"
        elif rsi < 35 and bb_width < 0.04:
            return "mean_reversion"
        elif bb_width < 0.03 and vol_spike >= 2.0:
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
        rr_ratio = (take_profit_1 - entry) / risk_per_unit if risk_per_unit > 0 else 0.0

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
