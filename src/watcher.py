"""
WatcherAgent — Market scanner.
Fetches all USDT pairs, filters by volume, scores by composite momentum,
and returns the top N candidates for the AnalyzerAgent.

v3.3 — Regime-aware + Futures short support:
  • In BEAR/CHOPPY regimes, additionally scans GateIO leveraged SHORT tokens
    (3S/5S suffix, e.g. BTC3S, ETH3S, SOL3S) tagged with direction="short".
  • In FUTURES mode, scans for bearish momentum on regular tokens to generate
    actual futures short candidates (not leveraged ETFs). These tokens are
    actively dumping and can be shorted on futures for profit.
  • Short candidates are scored with BEARISH momentum indicators.
  • The opportunity universe expands to 150+ symbols in bear mode.
"""
import asyncio
import time
from typing import Optional
from loguru import logger
import numpy as np

from .exchange_ccxt import ExchangeConnector
from .redis_client import RedisClient
from .metrics import signals_generated


# ── Leveraged ETF token patterns (Gate.io + Binance) ────────────────────────
# Spot-traded tokens that profit when the underlying falls (no margin needed).
# Gate.io: BTC3S/5S (short), BTC3L/5L (long)
# Binance: BTCDOWN (short), BTCUP (long)
SHORT_TOKEN_SUFFIXES = ("3S", "5S", "DOWN")
LONG_TOKEN_SUFFIXES  = ("3L", "5L", "UP")

# ── Stablecoin / near-stable blacklist ──────────────────────────────────────
# These tokens are pegged — they generate false momentum signals
# (e.g. USDC flagged as "momentum" on a 0.1% depeg). Never trade them.
_STABLE_BASES: frozenset[str] = frozenset({
    "USDC", "USDT", "BUSD", "FDUSD", "TUSD", "DAI", "USDP",
    "GUSD", "USDX", "USDD", "USDJ", "LUSD", "FRAX",
    "SUSD", "MUSD", "STBT", "USDE", "PYUSD",
    "WBTC", "WETH", "WBNB",  # wrapped tokens — track underlying, not wrapper
})


class WatcherAgent:
    """Scans exchange pairs and ranks by composite momentum score."""

    def __init__(
        self,
        exchange: ExchangeConnector,
        redis: Optional[RedisClient] = None,
        min_volume_24h_usd: float = 2_000_000.0,
        top_n: int = 20,
    ):
        self.exchange = exchange
        self.redis = redis
        self.min_volume_usd = min_volume_24h_usd
        self.top_n = top_n
        self._scan_count = 0

    async def scan(self, regime: str = "sideways", futures_mode: bool = False) -> list[dict]:
        """
        Scan all USDT pairs + regime-appropriate leveraged tokens.
        In BEAR/CHOPPY regimes also scans SHORT ETF tokens.
        In futures mode, also scans for bearish short candidates on regular tokens.
        Returns list of dicts: {symbol, score, ticker, timestamp, direction}
        """
        t0 = time.monotonic()
        self._scan_count += 1

        try:
            tickers = await self.exchange.fetch_tickers()
        except Exception as e:
            logger.error(f"[Watcher] Failed to fetch tickers: {e}")
            return []

        usdt_pairs = self.exchange.get_usdt_pairs()

        # ── In BEAR/CHOPPY regimes: lower volume bar & cast wider net ──────────
        bear_mode = regime in ("bear", "choppy")
        min_vol = self.min_volume_usd * 0.3 if bear_mode else self.min_volume_usd
        # Spread guard: leveraged tokens have natural wider spread.
        # Bull/sideways: 1.0% allows solid mid-caps (was 0.5% — too tight, cut most tokens).
        # Bear/choppy: 1.5% for leveraged short ETFs.
        max_spread_pct = 1.5 if bear_mode else 1.0

        long_candidates  = []
        short_candidates = []

        for symbol in usdt_pairs:
            if symbol not in tickers:
                continue
            ticker = tickers[symbol]
            vol_usd = (ticker.get("quoteVolume") or 0.0)

            last_price = ticker.get("last") or 0.0
            if last_price <= 0:
                continue

            # Spread guard
            bid = ticker.get("bid") or last_price
            ask = ticker.get("ask") or last_price
            mid = (bid + ask) / 2.0
            if mid > 0:
                spread_pct = (ask - bid) / mid * 100.0
                if spread_pct > max_spread_pct:
                    continue

            base = symbol.replace("/USDT", "")

            # ── Classify: short token, long token, or regular spot ────────
            is_short_token = any(base.endswith(sfx) for sfx in SHORT_TOKEN_SUFFIXES)
            is_long_token  = any(base.endswith(sfx) for sfx in LONG_TOKEN_SUFFIXES)

            if is_short_token:
                # Short tokens: collect separately, scored with bearish logic
                if bear_mode and vol_usd >= min_vol * 0.2:
                    short_candidates.append({
                        "symbol": symbol, "ticker": ticker,
                        "vol_usd": vol_usd, "direction": "short",
                    })
            elif is_long_token:
                # Long leveraged tokens: only in bull mode
                if not bear_mode and vol_usd >= min_vol:
                    long_candidates.append({
                        "symbol": symbol, "ticker": ticker,
                        "vol_usd": vol_usd, "direction": "long",
                    })
            else:
                # Regular token: skip stablecoins
                if base in _STABLE_BASES:
                    continue
                pct_24h = float(ticker.get("percentage") or 0.0)
                # Long momentum requires POSITIVE 24h move — skip anything down >3%
                if pct_24h >= -3.0 and vol_usd >= min_vol:
                    long_candidates.append({
                        "symbol": symbol, "ticker": ticker,
                        "vol_usd": vol_usd, "direction": "long",
                    })
                # Futures short: tokens actively dumping (24h < -1%) are short candidates
                # Only in futures mode — spot can't short regular tokens.
                if futures_mode and pct_24h <= -1.0 and vol_usd >= min_vol:
                    short_candidates.append({
                        "symbol": symbol, "ticker": ticker,
                        "vol_usd": vol_usd, "direction": "short",
                    })

        if not long_candidates and not short_candidates:
            logger.warning("[Watcher] No candidates after volume filter")
            return []

        # ── Score candidates in parallel ──────────────────────────────────────
        short_scored = []
        long_scored  = []

        if long_candidates:
            long_scored = await self._score_batch(long_candidates, inverted=False)
        if short_candidates:
            # Leveraged ETF shorts use inverted=True; futures shorts use for_short=True
            _has_futures_shorts = futures_mode and any(
                not any(c["symbol"].replace("/USDT", "").endswith(sfx)
                        for sfx in SHORT_TOKEN_SUFFIXES)
                for c in short_candidates
            )
            if _has_futures_shorts:
                # Split: leveraged ETF tokens vs regular futures shorts
                _etf_shorts = [c for c in short_candidates
                               if any(c["symbol"].replace("/USDT", "").endswith(sfx)
                                      for sfx in SHORT_TOKEN_SUFFIXES)]
                _futures_shorts = [c for c in short_candidates if c not in _etf_shorts]
                if _etf_shorts:
                    short_scored.extend(await self._score_batch(_etf_shorts, inverted=True))
                if _futures_shorts:
                    _fs = await self._score_batch(_futures_shorts, for_short=True)
                    short_scored.extend(_fs)
                    logger.info(f"[Watcher] Futures short: scored {len(_fs)} bearish candidates")
            elif bear_mode:
                short_scored = await self._score_batch(short_candidates, inverted=True)
                logger.info(f"[Watcher] Bear mode: scored {len(short_scored)} short-token candidates")

        all_scored = long_scored + short_scored
        all_scored.sort(key=lambda x: x["score"], reverse=True)

        # Give shorts their own quota so they don't crowd out longs.
        # In bear/choppy regimes both sides are active — give shorts 1/3 of top_n.
        # In bull/sideways keep the smaller 1/4 quota (shorts are rare).
        short_frac = 3 if regime in ("bear", "choppy") else 4
        n_shorts = min(len(short_scored), max(2, self.top_n // short_frac)) if short_scored else 0
        n_longs  = self.top_n - n_shorts

        top_longs  = sorted(long_scored,  key=lambda x: x["score"], reverse=True)[:n_longs]
        top_shorts = sorted(short_scored, key=lambda x: x["score"], reverse=True)[:n_shorts]
        top = top_longs + top_shorts

        # v7.5: Light whitelist boost — ensure top 3 whitelisted candidates
        # make it to the analyzer, even if their score is below cutoff.
        # Only 3 to avoid OHLCV fetch rate-limiting in the analyzer.
        try:
            from src.config import get_settings as _get_cfg
            _cfg = _get_cfg()
            _wl_raw = getattr(_cfg, "symbol_whitelist", "") or ""
            _wl = {s.strip().upper() for s in _wl_raw.split(",") if s.strip()}
            if _wl:
                _top_syms = {c["symbol"] for c in top}
                _wl_scored = [
                    c for c in all_scored
                    if (c.get("symbol", "").split("/")[0].upper() in _wl
                        and c["symbol"] not in _top_syms)
                ]
                _wl_scored.sort(key=lambda x: x.get("score", 0), reverse=True)
                _extra = _wl_scored[:3]
                if _extra:
                    top.extend(_extra)
                    logger.info(
                        f"[Watcher] Whitelist boost: +{len(_extra)} blue-chip "
                        f"({','.join(c['symbol'].split('/')[0] for c in _extra)})"
                    )
        except Exception as _wl_err:
            logger.debug(f"[Watcher] Whitelist boost failed: {_wl_err}")

        top.sort(key=lambda x: x["score"], reverse=True)

        elapsed = time.monotonic() - t0
        signals_generated.labels(agent="watcher").inc(len(top))
        long_count  = sum(1 for c in top if c.get("direction") == "long")
        short_count = sum(1 for c in top if c.get("direction") == "short")
        logger.info(
            f"[Watcher] Scanned {len(usdt_pairs)} pairs → "
            f"{long_count} long + {short_count} short candidates [{elapsed:.1f}s] "
            f"regime={regime}"
        )

        return top

    async def btc_momentum_score(self) -> dict:
        """Compute BTC momentum as a continuous score for graduated alt sizing.

        Returns dict with:
          score: float 0.0-1.2 (0=crash, 0.5=weak, 1.0=healthy, 1.2=strong bull)
          bullish: bool (backward compat — True if score >= 0.5)
          ema_gap_pct: float (EMA9-EMA21 gap %)
          rsi: float (14-period RSI)
          return_1h: float (1h price return %)

        Scoring model (continuous, not binary):
          - EMA gap component (40% weight): maps -2%..+2% gap to 0.0..1.0
          - RSI component (30% weight): maps 20..70 RSI to 0.0..1.0
          - 1h return component (30% weight): maps -3%..+3% return to 0.0..1.0
          - Bull bonus: score > 1.0 when all signals strongly positive (up to 1.2)
          - Crash floor: score = 0.0 when EMA gap < -1% AND RSI < 30

        Alts correlate 0.6-0.95 with BTC (SUI 0.93, ADA 0.91).
        This score scales alt position sizes proportionally instead of binary block.
        """
        try:
            candles = await self._fetch_ohlcv_cached("BTC/USDT", "1h", 50)
            if candles is None or len(candles) < 26:
                logger.warning("[Watcher] BTC momentum: insufficient data, returning 0.3")
                return {"score": 0.3, "bullish": False, "ema_gap_pct": 0.0, "rsi": 50.0, "return_1h": 0.0}

            closes = np.array([c[4] for c in candles], dtype=float)
            ema9 = _ema(closes, 9)
            ema21 = _ema(closes, 21)
            rsi = _compute_rsi(closes, 14)
            ema_gap_pct = (ema9 - ema21) / ema21 * 100 if ema21 > 0 else 0.0
            return_1h = (closes[-1] - closes[-13]) / closes[-13] * 100 if len(closes) >= 13 and closes[-13] > 0 else 0.0

            # ── EMA gap component (40%): -2% → 0.0, 0% → 0.5, +2% → 1.0
            ema_comp = min(max((ema_gap_pct + 2.0) / 4.0, 0.0), 1.0)

            # ── RSI component (30%): 20 → 0.0, 45 → 0.5, 70 → 1.0
            rsi_comp = min(max((rsi - 20.0) / 50.0, 0.0), 1.0)

            # ── 1h return component (30%): -3% → 0.0, 0% → 0.5, +3% → 1.0
            ret_comp = min(max((return_1h + 3.0) / 6.0, 0.0), 1.0)

            score = ema_comp * 0.4 + rsi_comp * 0.3 + ret_comp * 0.3

            # Bull bonus: when all three signals are strongly positive, allow up to 1.2x
            if ema_gap_pct > 0.5 and rsi > 55 and return_1h > 0.5:
                score = min(score * 1.2, 1.2)

            # Crash floor: genuine BTC crash → 0.0 (full block)
            if ema_gap_pct < -1.0 and rsi < 30:
                score = 0.0

            bullish = score >= 0.5
            label = f"{'BULL' if score >= 0.8 else 'OK' if bullish else 'WEAK' if score >= 0.3 else 'CRASH'} ({score:.2f})"
            logger.info(
                f"[Watcher] BTC momentum: EMA_gap={ema_gap_pct:+.2f}% RSI={rsi:.1f} "
                f"ret_1h={return_1h:+.2f}% → score={score:.2f} {label}"
            )
            return {
                "score": round(score, 3),
                "bullish": bullish,
                "ema_gap_pct": round(ema_gap_pct, 3),
                "rsi": round(rsi, 1),
                "return_1h": round(return_1h, 3),
            }
        except Exception as e:
            logger.warning(f"[Watcher] BTC momentum check failed: {e}, returning 0.3")
            return {"score": 0.3, "bullish": False, "ema_gap_pct": 0.0, "rsi": 50.0, "return_1h": 0.0}

    async def is_btc_trend_bullish(self) -> bool:
        """Backward-compatible wrapper — returns True if BTC momentum score >= 0.5."""
        result = await self.btc_momentum_score()
        return result["bullish"]

    async def _score_batch(self, candidates: list[dict], inverted: bool = False, for_short: bool = False) -> list[dict]:
        """Score a batch of candidates.
        inverted=True: leveraged ETF short-token scoring.
        for_short=True: futures short scoring (bearish momentum on regular tokens).
        """
        tasks = [self._score_symbol(c, inverted=inverted, for_short=for_short) for c in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if r is not None and not isinstance(r, Exception)]

    async def _score_symbol(self, candidate: dict, inverted: bool = False, for_short: bool = False) -> Optional[dict]:
        """
        Score a single symbol using 5m OHLCV + composite indicators.
        inverted=True: leveraged ETF short-token scoring (token rises when underlying falls).
        for_short=True: futures short scoring — reward bearish momentum on the token itself
                        (RSI 25-45, MACD<0, red candles, EMA death cross, negative ROC).
        """
        symbol = candidate["symbol"]
        ticker = candidate["ticker"]
        direction = candidate.get("direction", "long")

        candles = await self._fetch_ohlcv_cached(symbol, "5m", 60)
        if candles is None or len(candles) < 30:
            return None

        candles_np = np.array(candles)
        closes = candles_np[:, 4].astype(float)
        volumes = candles_np[:, 5].astype(float)

        score = 0.0
        score_breakdown = {}

        # ── Volume spike (same for both directions — momentum is momentum) ─
        avg_vol = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes))
        curr_vol = float(volumes[-1])
        vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0
        if vol_ratio >= 10.0:
            vol_pts = 40.0
        elif vol_ratio >= 5.0:
            vol_pts = 30.0 + (vol_ratio - 5.0) * 2.0
        elif vol_ratio >= 3.0:
            vol_pts = 20.0 + (vol_ratio - 3.0) * 5.0
        elif vol_ratio >= 2.0:
            vol_pts = 10.0 + (vol_ratio - 2.0) * 10.0
        elif vol_ratio >= 1.5:
            vol_pts = 3.0 + (vol_ratio - 1.5) * 14.0
        else:
            vol_pts = 0.0
        vol_pts = min(40.0, vol_pts)
        score += vol_pts
        score_breakdown["volume_spike"] = vol_pts

        # ── RSI ───────────────────────────────────────────────────────────
        rsi = _compute_rsi(closes, 14)
        if for_short:
            # FUTURES SHORT: reward bearish RSI zone 25-45 (downward momentum,
            # not yet oversold/bouncing). RSI > 55 = bullish = bad for short.
            if 25 <= rsi <= 45:
                rsi_pts = 15.0
            elif 45 < rsi <= 50:
                rsi_pts = 8.0
            elif 20 <= rsi < 25:
                rsi_pts = 5.0  # too oversold, bounce risk
            elif rsi < 20:
                rsi_pts = 0.0  # heavily oversold, don't short
            else:
                rsi_pts = max(0.0, 15.0 * (55.0 - rsi) / 15.0)  # fade as RSI rises
        elif not inverted:
            # LONG: favour upward momentum zone 55-75
            if 55 <= rsi <= 75:
                rsi_pts = 15.0
            elif 50 <= rsi < 55:
                rsi_pts = 10.0
            elif rsi > 75:
                rsi_pts = max(0.0, 15.0 * (90.0 - rsi) / 15.0)
            else:
                rsi_pts = max(0.0, 15.0 * (rsi - 35.0) / 20.0)
        else:
            # SHORT token: these tokens rise when underlying falls.
            # Score highest when RSI of the SHORT TOKEN itself is in bullish zone 55-75
            if 55 <= rsi <= 75:
                rsi_pts = 15.0
            elif 50 <= rsi < 55:
                rsi_pts = 10.0
            elif rsi > 75:
                rsi_pts = max(0.0, 15.0 * (90.0 - rsi) / 15.0)
            else:
                rsi_pts = max(0.0, 15.0 * (rsi - 35.0) / 20.0)
        score += rsi_pts
        score_breakdown["rsi"] = rsi_pts

        # ── MACD histogram ────────────────────────────────────────────────
        macd_hist = _compute_macd_hist(closes, 12, 26, 9)
        if for_short:
            # FUTURES SHORT: reward negative MACD histogram (bearish momentum)
            macd_pts = min(20.0, max(0.0, abs(macd_hist) * 60.0)) if macd_hist < 0 else 0.0
        elif not inverted:
            macd_pts = min(20.0, max(0.0, macd_hist * 60.0)) if macd_hist > 0 else 0.0
        else:
            # Short token: MACD > 0 means the short token is trending up = good
            macd_pts = min(20.0, max(0.0, macd_hist * 60.0)) if macd_hist > 0 else 0.0
        score += macd_pts
        score_breakdown["macd"] = macd_pts

        # ── Candle direction ──────────────────────────────────────────────
        if len(closes) >= 4:
            if for_short:
                # FUTURES SHORT: consecutive RED candles = selling pressure
                momentum_count = sum(1 for i in range(-3, 0) if closes[i] < closes[i - 1])
            elif not inverted:
                # LONG: consecutive green candles
                momentum_count = sum(1 for i in range(-3, 0) if closes[i] > closes[i - 1])
            else:
                # SHORT TOKEN: consecutive green candles on the token itself
                momentum_count = sum(1 for i in range(-3, 0) if closes[i] > closes[i - 1])
            momentum_pts = momentum_count * 6.0
        else:
            momentum_pts = 0.0
        score += momentum_pts
        score_breakdown["momentum"] = momentum_pts

        # ── OBV trend (10-bar slope) ──────────────────────────────────────
        obv = _compute_obv(closes, volumes)
        if len(obv) >= 10:
            obv_slope = (obv[-1] - obv[-10]) / (abs(obv[-10]) + 1e-9)
            if for_short:
                # FUTURES SHORT: negative OBV = money flowing OUT = selling pressure
                obv_pts = min(15.0, max(0.0, abs(obv_slope) * 15.0)) if obv_slope < 0 else 0.0
            elif not inverted:
                obv_pts = min(15.0, max(0.0, obv_slope * 15.0))
            else:
                # Short token: positive OBV on the token = money flowing into it = good
                obv_pts = min(15.0, max(0.0, obv_slope * 15.0))
        else:
            obv_pts = 0.0
        score += obv_pts
        score_breakdown["obv"] = obv_pts

        # ── Rate of Change (12-bar) ───────────────────────────────────────
        if len(closes) >= 13:
            roc = (closes[-1] - closes[-13]) / closes[-13] * 100
            if for_short:
                # FUTURES SHORT: reward negative ROC (price falling)
                if roc <= -3.0:
                    roc_pts = min(20.0, abs(roc) * 2.5)
                elif roc < 0:
                    roc_pts = abs(roc) * 3.0
                else:
                    roc_pts = 0.0
            elif not inverted:
                if roc >= 3.0:
                    roc_pts = min(20.0, roc * 2.5)
                elif roc > 0:
                    roc_pts = roc * 3.0
                else:
                    roc_pts = 0.0
            else:
                if roc >= 3.0:
                    roc_pts = min(20.0, roc * 2.5)
                elif roc > 0:
                    roc_pts = roc * 3.0
                else:
                    roc_pts = 0.0
        else:
            roc_pts = 0.0
        score += roc_pts
        score_breakdown["roc"] = roc_pts

        # ── EMA alignment ─────────────────────────────────────────────────
        ema9 = _ema(closes, 9)
        ema21 = _ema(closes, 21)
        ema50 = _ema(closes, 50) if len(closes) >= 50 else None
        if for_short:
            # FUTURES SHORT: reward bearish EMA alignment (death cross)
            ema_aligned = ema9 < ema21
            ema_fully_aligned = (ema9 < ema21 < ema50) if ema50 is not None else False
        elif not inverted:
            ema_aligned = ema9 > ema21
            ema_fully_aligned = (ema9 > ema21 > ema50) if ema50 is not None else False
        else:
            ema_aligned = ema9 > ema21
            ema_fully_aligned = (ema9 > ema21 > ema50) if ema50 is not None else False
        ema_pts = 15.0 if ema_fully_aligned else (8.0 if ema_aligned else 0.0)
        score += ema_pts
        score_breakdown["ema"] = ema_pts

        # ── 1h price return (from 5m candles) — THE momentum signal ─────────
        # This directly captures "SOL just pumped 5%". If close now > close 12 bars
        # ago (= 1 hour on 5m) the token is ACTUALLY moving, not just noisy.
        if len(closes) >= 13:
            return_1h = (closes[-1] - closes[-13]) / closes[-13] * 100.0
        else:
            return_1h = 0.0
        if for_short:
            # FUTURES SHORT: reward negative 1h return (token is DUMPING)
            abs_ret = abs(return_1h)
            if return_1h <= -5.0:
                ret1h_pts = 35.0
            elif return_1h <= -3.0:
                ret1h_pts = 25.0
            elif return_1h <= -2.0:
                ret1h_pts = 18.0
            elif return_1h <= -1.0:
                ret1h_pts = 10.0
            elif return_1h <= -0.5:
                ret1h_pts = 5.0
            else:
                ret1h_pts = 0.0
        elif not inverted:
            if return_1h >= 5.0:
                ret1h_pts = 35.0
            elif return_1h >= 3.0:
                ret1h_pts = 25.0
            elif return_1h >= 2.0:
                ret1h_pts = 18.0
            elif return_1h >= 1.0:
                ret1h_pts = 10.0
            elif return_1h >= 0.5:
                ret1h_pts = 5.0
            else:
                ret1h_pts = 0.0
        else:
            if return_1h >= 5.0:
                ret1h_pts = 35.0
            elif return_1h >= 3.0:
                ret1h_pts = 25.0
            elif return_1h >= 1.0:
                ret1h_pts = 10.0
            else:
                ret1h_pts = 0.0
        score += ret1h_pts
        score_breakdown["return_1h"] = ret1h_pts

        # ── 24h trend bonus — momentum requires strong daily price action ───
        pct_change_24h = float(ticker.get("percentage") or 0.0)
        if for_short:
            # FUTURES SHORT: reward negative 24h trend (sustained selling)
            abs_24h = abs(pct_change_24h)
            if pct_change_24h <= -10.0:
                trend_pts = 25.0
            elif pct_change_24h <= -5.0:
                trend_pts = 18.0
            elif pct_change_24h <= -2.0:
                trend_pts = 10.0
            elif pct_change_24h <= -1.0:
                trend_pts = 5.0
            else:
                trend_pts = 0.0
        else:
            if pct_change_24h >= 10.0:
                trend_pts = 25.0
            elif pct_change_24h >= 5.0:
                trend_pts = 18.0
            elif pct_change_24h >= 2.0:
                trend_pts = 10.0
            elif pct_change_24h >= 1.0:
                trend_pts = 5.0
            else:
                trend_pts = 0.0
        score += trend_pts
        score_breakdown["trend_24h"] = trend_pts

        # ── ANTI-CHASE penalty ───────────────────────────────────────────
        if for_short:
            # FUTURES SHORT anti-chase: if price bounced >2% from recent LOW,
            # the dump is OVER and it's recovering — don't short a reversal.
            if len(candles_np) >= 12:
                recent_lows = candles_np[-12:, 3].astype(float)  # column 3 = low
                recent_low = float(np.min(recent_lows))
                if recent_low > 0 and closes[-1] > 0:
                    bounce_pct = (closes[-1] - recent_low) / recent_low * 100.0
                    if bounce_pct >= 5.0:
                        chase_penalty = -35.0
                    elif bounce_pct >= 3.0:
                        chase_penalty = -25.0
                    elif bounce_pct >= 2.0:
                        chase_penalty = -15.0
                    elif bounce_pct >= 1.0:
                        chase_penalty = -8.0
                    else:
                        chase_penalty = 0.0
                    score += chase_penalty
                    score_breakdown["anti_chase"] = chase_penalty
            # Penalty for GREEN candle sequence (momentum reversing UP)
            if len(closes) >= 5:
                green_count = sum(1 for i in range(-4, 0) if closes[i] > closes[i - 1])
                if green_count >= 3:
                    green_penalty = -12.0
                    score += green_penalty
                    score_breakdown["bullish_candles_penalty"] = green_penalty
        else:
            # LONG anti-chase: pullback from recent high
            if len(candles_np) >= 12:
                recent_highs = candles_np[-12:, 2].astype(float)  # column 2 = high
                recent_high = float(np.max(recent_highs))
                if recent_high > 0 and closes[-1] > 0:
                    pullback_pct = (recent_high - closes[-1]) / recent_high * 100.0
                    if pullback_pct >= 5.0:
                        chase_penalty = -35.0
                    elif pullback_pct >= 3.0:
                        chase_penalty = -25.0
                    elif pullback_pct >= 2.0:
                        chase_penalty = -15.0
                    elif pullback_pct >= 1.0:
                        chase_penalty = -8.0
                    else:
                        chase_penalty = 0.0
                    score += chase_penalty
                    score_breakdown["anti_chase"] = chase_penalty

            # Penalty for RED candle sequence (bearish) on longs
            if len(closes) >= 5 and not inverted:
                red_count = sum(1 for i in range(-4, 0) if closes[i] < closes[i - 1])
                if red_count >= 3:
                    red_penalty = -12.0
                    score += red_penalty
                    score_breakdown["bearish_candles"] = red_penalty
        price = ticker.get("last") or 0.0
        vol_usd = candidate["vol_usd"]
        setup_type = "momentum_short" if (inverted or for_short) else "momentum"

        return {
            "symbol": symbol,
            "score": round(score, 2),
            "score_breakdown": score_breakdown,
            "rsi": round(rsi, 1),
            "pct_change_24h": round(pct_change_24h, 2),
            "price": price,
            "vol_usd": vol_usd,
            "macd_hist": round(macd_hist, 6),
            "vol_ratio": round(vol_ratio, 2),
            "ema_aligned": ema_fully_aligned,
            "direction": direction,
            "setup_type": setup_type,
            "timestamp": int(time.time()),
        }

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
            logger.debug(f"[Watcher] OHLCV fetch failed for {symbol}: {e}")
            return None


# ── Indicator helpers ────────────────────────────────────────────────────────

def _compute_rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains[-period:]))
    avg_loss = float(np.mean(losses[-period:]))
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_macd_hist(closes: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> float:
    """Compute MACD histogram in O(n) using incremental EMA series."""
    if len(closes) < slow + signal:
        return 0.0

    # Build full EMA-fast and EMA-slow series in a single forward pass — O(n)
    k_fast = 2.0 / (fast + 1)
    k_slow = 2.0 / (slow + 1)
    k_sig = 2.0 / (signal + 1)

    ema_fast = float(np.mean(closes[:fast]))
    ema_slow = float(np.mean(closes[:slow]))

    # Advance fast EMA to the slow start point
    for price in closes[fast:slow]:
        ema_fast = float(price) * k_fast + ema_fast * (1 - k_fast)

    # Build MACD line from slow start onward
    macd_series: list[float] = []
    for price in closes[slow:]:
        ema_fast = float(price) * k_fast + ema_fast * (1 - k_fast)
        ema_slow = float(price) * k_slow + ema_slow * (1 - k_slow)
        macd_series.append(ema_fast - ema_slow)

    if len(macd_series) < signal:
        return 0.0

    # Build signal line by EMA of MACD series — single pass
    sig = float(np.mean(macd_series[:signal]))
    for val in macd_series[signal:]:
        sig = val * k_sig + sig * (1 - k_sig)

    return float(macd_series[-1] - sig)



def _compute_obv(closes: np.ndarray, volumes: np.ndarray) -> np.ndarray:
    obv = np.zeros(len(closes))
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv[i] = obv[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            obv[i] = obv[i - 1] - volumes[i]
        else:
            obv[i] = obv[i - 1]
    return obv


def _ema(closes: np.ndarray, period: int) -> float:
    if len(closes) < period:
        return float(closes[-1]) if len(closes) > 0 else 0.0
    k = 2.0 / (period + 1)
    ema = float(np.mean(closes[:period]))
    for price in closes[period:]:
        ema = float(price) * k + ema * (1 - k)
    return ema
