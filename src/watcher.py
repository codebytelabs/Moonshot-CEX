"""
WatcherAgent — Market scanner.
Fetches all USDT pairs, filters by volume, scores by composite momentum,
and returns the top N candidates for the AnalyzerAgent.
"""
import asyncio
import time
from typing import Optional
from loguru import logger
import numpy as np

from .exchange_ccxt import ExchangeConnector
from .redis_client import RedisClient
from .metrics import signals_generated


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

    async def scan(self) -> list[dict]:
        """
        Scan all USDT pairs, filter by volume, score, and return top N candidates.
        Returns list of dicts: {symbol, score, ticker, timestamp}
        """
        t0 = time.monotonic()
        self._scan_count += 1

        try:
            tickers = await self.exchange.fetch_tickers()
        except Exception as e:
            logger.error(f"[Watcher] Failed to fetch tickers: {e}")
            return []

        usdt_pairs = self.exchange.get_usdt_pairs()
        candidates = []

        for symbol in usdt_pairs:
            if symbol not in tickers:
                continue
            ticker = tickers[symbol]
            vol_usd = (ticker.get("quoteVolume") or 0.0)
            if vol_usd < self.min_volume_usd:
                continue

            last_price = ticker.get("last") or 0.0
            if last_price <= 0:
                continue

            # Spread guard: skip if bid-ask spread > 0.5% (slippage killer)
            bid = ticker.get("bid") or last_price
            ask = ticker.get("ask") or last_price
            mid = (bid + ask) / 2.0
            if mid > 0:
                spread_pct = (ask - bid) / mid * 100.0
                if spread_pct > 0.5:
                    continue

            candidates.append({"symbol": symbol, "ticker": ticker, "vol_usd": vol_usd})


        if not candidates:
            logger.warning("[Watcher] No candidates after volume filter")
            return []

        scored = await self._score_candidates(candidates)
        scored.sort(key=lambda x: x["score"], reverse=True)
        top = scored[: self.top_n]

        elapsed = time.monotonic() - t0
        signals_generated.labels(agent="watcher").inc(len(top))
        logger.info(f"[Watcher] Scanned {len(candidates)} pairs → {len(top)} candidates [{elapsed:.1f}s]")

        return top

    async def _score_candidates(self, candidates: list[dict]) -> list[dict]:
        """Fetch 5m OHLCV for each candidate and compute momentum score."""
        tasks = [self._score_symbol(c) for c in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        scored = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                continue
            if res is not None:
                scored.append(res)
        return scored

    async def _score_symbol(self, candidate: dict) -> Optional[dict]:
        """Score a single symbol using 5m OHLCV + composite indicators."""
        symbol = candidate["symbol"]
        ticker = candidate["ticker"]

        candles = await self._fetch_ohlcv_cached(symbol, "5m", 60)
        if candles is None or len(candles) < 30:
            return None

        candles_np = np.array(candles)
        closes = candles_np[:, 4].astype(float)
        volumes = candles_np[:, 5].astype(float)

        score = 0.0
        score_breakdown = {}

        # ── Volume spike (PRIMARY signal for momentum strategy) ──────────
        avg_vol = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes))
        curr_vol = float(volumes[-1])
        vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0
        if vol_ratio >= 10.0:
            vol_pts = 60.0
        elif vol_ratio >= 5.0:
            vol_pts = 45.0 + (vol_ratio - 5.0) * 3.0
        elif vol_ratio >= 3.0:
            vol_pts = 30.0 + (vol_ratio - 3.0) * 7.5
        elif vol_ratio >= 2.0:
            vol_pts = 15.0 + (vol_ratio - 2.0) * 15.0
        elif vol_ratio >= 1.5:
            vol_pts = 5.0 + (vol_ratio - 1.5) * 20.0
        else:
            vol_pts = 0.0
        vol_pts = min(60.0, vol_pts)
        score += vol_pts
        score_breakdown["volume_spike"] = vol_pts

        # ── RSI — favour momentum zone 55-75 ─────────────────────────────
        rsi = _compute_rsi(closes, 14)
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

        # ── MACD histogram — positive and growing ────────────────────────
        macd_hist = _compute_macd_hist(closes, 12, 26, 9)
        macd_pts = min(20.0, max(0.0, macd_hist * 60.0)) if macd_hist > 0 else 0.0
        score += macd_pts
        score_breakdown["macd"] = macd_pts

        # ── Momentum continuation (consecutive green candles) ─────────────
        if len(closes) >= 4:
            green_count = sum(1 for i in range(-3, 0) if closes[i] > closes[i - 1])
            momentum_pts = green_count * 6.0
        else:
            momentum_pts = 0.0
        score += momentum_pts
        score_breakdown["momentum"] = momentum_pts

        # ── OBV trend (10-bar slope) ──────────────────────────────────────
        obv = _compute_obv(closes, volumes)
        if len(obv) >= 10:
            obv_slope = (obv[-1] - obv[-10]) / (abs(obv[-10]) + 1e-9)
            obv_pts = min(15.0, max(0.0, obv_slope * 15.0))
        else:
            obv_pts = 0.0
        score += obv_pts
        score_breakdown["obv"] = obv_pts

        # ── Rate of Change (12-bar) — amplified for strong momentum ───────
        if len(closes) >= 13:
            roc = (closes[-1] - closes[-13]) / closes[-13] * 100
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

        # ── EMA alignment (EMA9 > EMA21 > EMA50) ─────────────────────────
        ema9 = _ema(closes, 9)
        ema21 = _ema(closes, 21)
        ema50 = _ema(closes, 50) if len(closes) >= 50 else None
        ema_aligned = ema9 > ema21
        if ema50 is not None:
            ema_fully_aligned = ema9 > ema21 > ema50
        else:
            ema_fully_aligned = False
        ema_pts = 15.0 if ema_fully_aligned else (8.0 if ema_aligned else 0.0)
        score += ema_pts
        score_breakdown["ema"] = ema_pts

        pct_change_24h = ticker.get("percentage") or 0.0
        price = ticker.get("last") or 0.0
        vol_usd = candidate["vol_usd"]

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
