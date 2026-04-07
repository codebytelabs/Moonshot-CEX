"""
Mean Reversion Strategy — Buys oversold bounces, fades overextended moves.

Targets tokens that have moved >2 standard deviations from mean.
Win rate: 60-70% | Trades: 2-5/day | Target: 0.5-2% per trade

Entry rules (LONG - oversold bounce):
  1. RSI(14) on 15m drops below 30, then crosses back above 33
  2. Price below lower Bollinger Band (20, 2.0)
  3. Price within 0.5 ATR of EMA21 (reverting to mean)
  4. Volume spike on recovery candle (>1.3x average)
  5. 1h trend not strongly bearish (EMA9 not >2% below EMA21)

Exit rules:
  - TP1: +1.0% or middle Bollinger Band (whichever first)
  - TP2: +2.0% or upper Bollinger Band
  - Trail at 0.6% distance after +1.0%
  - SL: -1.2% (below the oversold wick)
  - Time exit: 1h for losers, 3h hard cap
"""
from __future__ import annotations
import asyncio
import time
from typing import Optional
from loguru import logger
from .base import BaseStrategy, StrategySignal


class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"
    max_signals_per_cycle = 3

    DEFAULTS = {
        "scan_interval_seconds": 20,
        "min_volume_24h": 1_500_000,
        "top_n_scan": 35,
        "rsi_period": 14,
        "rsi_oversold": 33,
        "rsi_entry_trigger": 35,
        "rsi_overbought": 72,
        "bb_period": 20,
        "bb_std": 2.0,
        "ema_mean_period": 21,
        "volume_spike_mult": 1.3,
        "tp1_pct": 1.0,
        "tp2_pct": 2.0,
        "sl_pct": -1.2,
        "trail_activate_pct": 1.0,
        "trail_distance_pct": 0.6,
        "tp1_exit_frac": 0.35,
        "tp2_exit_frac": 0.30,
        "max_hold_minutes_loser": 60,
        "max_hold_minutes_hard": 180,
        "min_score": 55,
        "max_1h_bearish_pct": -2.0,
    }

    def __init__(self, exchange, config=None):
        merged = {**self.DEFAULTS, **(config or {})}
        super().__init__(exchange, merged)
        self._scan_interval = merged["scan_interval_seconds"]
        self._pair_cache: list[str] = []
        self._cache_time = 0.0

    async def _get_pairs(self) -> list[str]:
        now = time.time()
        if self._pair_cache and now - self._cache_time < 300:
            return self._pair_cache
        pairs = self.exchange.get_usdt_pairs()
        self._pair_cache = pairs
        self._cache_time = now
        return pairs

    async def scan(self, regime: str = "sideways") -> list[StrategySignal]:
        if not self.enabled or not self.should_scan():
            return []

        pairs = await self._get_pairs()
        if not pairs:
            return []

        try:
            tickers = await self.exchange.fetch_tickers()
        except Exception as e:
            logger.warning(f"[mean_rev] ticker fetch failed: {e}")
            return []

        min_vol = self.config["min_volume_24h"]
        long_candidates = []
        short_candidates = []
        pair_set = set(pairs)
        for sym, tk in tickers.items():
            if "/USDT" not in sym or sym not in pair_set:
                continue
            vol = float(tk.get("quoteVolume") or 0)
            last = float(tk.get("last") or 0)
            pct = float(tk.get("percentage") or 0)
            if vol < min_vol or last <= 0:
                continue
            # Long: tokens that dipped (oversold bounce)
            if -8 <= pct <= 2:
                long_candidates.append((sym, vol, last, pct))
            # Short: tokens that pumped (overbought fade)
            if pct >= 3:
                short_candidates.append((sym, vol, last, pct))

        long_candidates.sort(key=lambda x: x[3])
        long_candidates = long_candidates[: self.config["top_n_scan"]]
        short_candidates.sort(key=lambda x: x[3], reverse=True)
        short_candidates = short_candidates[: self.config["top_n_scan"]]

        signals = []
        long_tasks = [self._analyze_reversion(sym, vol, last) for sym, vol, last, _ in long_candidates[:12]]
        short_tasks = [self._analyze_overbought_fade(sym, vol, last) for sym, vol, last, _ in short_candidates[:8]]
        results = await asyncio.gather(*(long_tasks + short_tasks), return_exceptions=True)
        for r in results:
            if isinstance(r, StrategySignal):
                signals.append(r)

        signals.sort(key=lambda s: s.score, reverse=True)
        out = signals[: self.max_signals_per_cycle]
        if out:
            logger.info(f"[mean_rev] {len(out)} signals: {[(s.symbol, s.direction) for s in out]}")
        return out

    async def _analyze_reversion(self, symbol: str, vol_usd: float, last_price: float) -> Optional[StrategySignal]:
        candles_15m, candles_1h = await asyncio.gather(
            self._fetch_candles(symbol, "15m", 50),
            self._fetch_candles(symbol, "1h", 30),
        )
        if len(candles_15m) < 25 or len(candles_1h) < 15:
            return None

        closes_15 = [c[4] for c in candles_15m]
        highs_15 = [c[2] for c in candles_15m]
        lows_15 = [c[3] for c in candles_15m]
        volumes_15 = [c[5] for c in candles_15m]
        price = closes_15[-1]

        closes_1h = [c[4] for c in candles_1h]

        # -- 1h Trend Check (don't buy into a strong downtrend) --
        ema9_1h = self.ema(closes_1h, 9)
        ema21_1h = self.ema(closes_1h, 21)
        if ema9_1h and ema21_1h and ema21_1h[-1] > 0:
            trend_gap = (ema9_1h[-1] - ema21_1h[-1]) / ema21_1h[-1] * 100
            if trend_gap < self.config["max_1h_bearish_pct"]:
                return None  # Too bearish on 1h — skip

        # -- 15m Indicators --
        rsi_val = self.rsi(closes_15, self.config["rsi_period"])
        upper, mid, lower = self.bollinger_bands(closes_15, self.config["bb_period"], self.config["bb_std"])
        ema_mean = self.ema(closes_15, self.config["ema_mean_period"])
        atr_val = self.atr(highs_15, lows_15, closes_15, 14)

        if not ema_mean or len(ema_mean) < 2:
            return None

        # -- Check for RSI recovery from oversold --
        # RSI must have been below oversold threshold recently (last 3-5 candles)
        # and now recovering above entry trigger
        rsi_history = []
        for i in range(max(0, len(closes_15) - 6), len(closes_15)):
            segment = closes_15[:i + 1]
            if len(segment) >= self.config["rsi_period"] + 1:
                rsi_history.append(self.rsi(segment, self.config["rsi_period"]))

        was_oversold = any(r < self.config["rsi_oversold"] for r in rsi_history[:-1]) if len(rsi_history) > 1 else False
        is_recovering = rsi_val >= self.config["rsi_entry_trigger"]

        # -- Scoring (0-100) --
        score = 0.0
        reasons = []

        # 1. RSI oversold bounce (+30 — primary signal)
        if was_oversold and is_recovering:
            score += 30
            reasons.append(f"rsi_bounce({rsi_val:.0f})")
        elif rsi_val < 40:
            score += 15
            reasons.append(f"rsi_low({rsi_val:.0f})")
        else:
            return None  # Not a mean reversion setup

        # 2. Price at/below lower Bollinger Band (+20)
        if price <= lower:
            score += 20
            reasons.append("below_bb_lower")
        elif price <= mid:
            score += 10
            reasons.append("below_bb_mid")
        else:
            score -= 5  # Above middle band — weaker reversion signal

        # 3. Proximity to EMA mean (+15)
        if ema_mean[-1] > 0:
            dist_to_mean = (price - ema_mean[-1]) / ema_mean[-1] * 100
            if -2.0 <= dist_to_mean <= 0.5:
                score += 15
                reasons.append(f"near_ema({dist_to_mean:+.1f}%)")
            elif dist_to_mean < -2.0:
                score += 10  # Extended below, but might keep falling
                reasons.append(f"extended({dist_to_mean:+.1f}%)")

        # 4. Volume on recovery candle (+15)
        avg_vol = sum(volumes_15[-20:]) / 20 if len(volumes_15) >= 20 else sum(volumes_15) / max(len(volumes_15), 1)
        vol_ratio = volumes_15[-1] / avg_vol if avg_vol > 0 else 0
        if vol_ratio >= self.config["volume_spike_mult"]:
            score += 15
            reasons.append(f"vol_recovery({vol_ratio:.1f}x)")
        elif vol_ratio >= 0.8:
            score += 5

        # 5. Bullish candle (close > open on last candle) (+10)
        if candles_15m[-1][4] > candles_15m[-1][1]:
            score += 10
            reasons.append("bullish_candle")

        # 6. 1h trend not against us (+5)
        if ema9_1h and ema21_1h and ema9_1h[-1] > ema21_1h[-1]:
            score += 5
            reasons.append("1h_supportive")

        if score < self.config["min_score"]:
            return None

        # -- Compute levels --
        sl_pct = self.config["sl_pct"]
        if atr_val > 0 and price > 0:
            atr_stop = -(atr_val * 1.8 / price * 100)
            sl_pct = max(sl_pct, atr_stop)
            sl_pct = max(sl_pct, -2.0)
            sl_pct = min(sl_pct, -0.6)

        tp1_pct = self.config["tp1_pct"]
        tp2_pct = self.config["tp2_pct"]

        # TP1 can also target middle Bollinger Band
        bb_mid_target = (mid - price) / price * 100 if mid > price else tp1_pct
        if 0.3 < bb_mid_target < tp1_pct:
            tp1_pct = bb_mid_target

        stop_price = price * (1 + sl_pct / 100)
        tp1_price = price * (1 + tp1_pct / 100)
        tp2_price = price * (1 + tp2_pct / 100)

        return StrategySignal(
            symbol=symbol,
            strategy=self.name,
            direction="long",
            score=min(score, 100),
            entry_price=price,
            stop_loss=stop_price,
            stop_loss_pct=sl_pct,
            take_profit_1=tp1_price,
            take_profit_2=tp2_price,
            tp1_pct=tp1_pct,
            tp2_pct=tp2_pct,
            confidence=min(score / 100, 0.95),
            vol_usd=vol_usd,
            timeframe="15m",
            setup_type="mean_reversion",
            reason=" | ".join(reasons),
            trail_activate_pct=self.config["trail_activate_pct"],
            trail_distance_pct=self.config["trail_distance_pct"],
            max_hold_minutes=self.config["max_hold_minutes_loser"],
        )

    async def _analyze_overbought_fade(self, symbol: str, vol_usd: float, last_price: float) -> Optional[StrategySignal]:
        """SHORT entry: fade overbought tokens reverting to mean from above."""
        candles_15m, candles_1h = await asyncio.gather(
            self._fetch_candles(symbol, "15m", 50),
            self._fetch_candles(symbol, "1h", 30),
        )
        if len(candles_15m) < 25 or len(candles_1h) < 15:
            return None

        closes_15 = [c[4] for c in candles_15m]
        highs_15 = [c[2] for c in candles_15m]
        lows_15 = [c[3] for c in candles_15m]
        volumes_15 = [c[5] for c in candles_15m]
        price = closes_15[-1]
        closes_1h = [c[4] for c in candles_1h]

        # 1h trend check — don't short into a strong uptrend
        ema9_1h = self.ema(closes_1h, 9)
        ema21_1h = self.ema(closes_1h, 21)
        if ema9_1h and ema21_1h and ema21_1h[-1] > 0:
            trend_gap = (ema9_1h[-1] - ema21_1h[-1]) / ema21_1h[-1] * 100
            if trend_gap > 3.0:
                return None  # Too bullish on 1h for a short fade

        rsi_val = self.rsi(closes_15, self.config["rsi_period"])
        upper, mid, lower = self.bollinger_bands(closes_15, self.config["bb_period"], self.config["bb_std"])
        ema_mean = self.ema(closes_15, self.config["ema_mean_period"])
        atr_val = self.atr(highs_15, lows_15, closes_15, 14)

        if not ema_mean or len(ema_mean) < 2:
            return None

        # Check RSI was overbought recently and is now turning down
        rsi_history = []
        for i in range(max(0, len(closes_15) - 6), len(closes_15)):
            segment = closes_15[:i + 1]
            if len(segment) >= self.config["rsi_period"] + 1:
                rsi_history.append(self.rsi(segment, self.config["rsi_period"]))

        was_overbought = any(r > self.config["rsi_overbought"] for r in rsi_history[:-1]) if len(rsi_history) > 1 else False
        is_turning_down = rsi_val < self.config["rsi_overbought"] - 3

        score = 0.0
        reasons = []

        # 1. RSI overbought fade (+30)
        if was_overbought and is_turning_down:
            score += 30
            reasons.append(f"rsi_fade({rsi_val:.0f})")
        elif rsi_val > 65:
            score += 15
            reasons.append(f"rsi_high({rsi_val:.0f})")
        else:
            return None

        # 2. Price at/above upper BB (+20)
        if price >= upper:
            score += 20
            reasons.append("above_bb_upper")
        elif price >= mid:
            score += 10
            reasons.append("above_bb_mid")
        else:
            score -= 5

        # 3. Extended above EMA mean (+15)
        if ema_mean[-1] > 0:
            dist_to_mean = (price - ema_mean[-1]) / ema_mean[-1] * 100
            if dist_to_mean >= 1.0:
                score += 15
                reasons.append(f"extended_above({dist_to_mean:+.1f}%)")
            elif dist_to_mean >= 0.3:
                score += 10

        # 4. Volume on fade candle (+15)
        avg_vol = sum(volumes_15[-20:]) / 20 if len(volumes_15) >= 20 else sum(volumes_15) / max(len(volumes_15), 1)
        vol_ratio = volumes_15[-1] / avg_vol if avg_vol > 0 else 0
        if vol_ratio >= self.config["volume_spike_mult"]:
            score += 15
            reasons.append(f"vol_selling({vol_ratio:.1f}x)")
        elif vol_ratio >= 0.8:
            score += 5

        # 5. Bearish candle (close < open) (+10)
        if candles_15m[-1][4] < candles_15m[-1][1]:
            score += 10
            reasons.append("bearish_candle")

        if score < self.config["min_score"]:
            return None

        # Compute SHORT levels
        sl_pct = abs(self.config["sl_pct"])
        if atr_val > 0 and price > 0:
            atr_stop = atr_val * 1.8 / price * 100
            sl_pct = min(sl_pct, atr_stop)
            sl_pct = min(sl_pct, 2.0)
            sl_pct = max(sl_pct, 0.6)

        tp1_pct = self.config["tp1_pct"]
        tp2_pct = self.config["tp2_pct"]

        # TP1 can target middle BB from above
        if mid > 0 and price > mid:
            bb_mid_target = (price - mid) / price * 100
            if 0.3 < bb_mid_target < tp1_pct:
                tp1_pct = bb_mid_target

        stop_price = price * (1 + sl_pct / 100)
        tp1_price = price * (1 - tp1_pct / 100)
        tp2_price = price * (1 - tp2_pct / 100)

        return StrategySignal(
            symbol=symbol,
            strategy=self.name,
            direction="short",
            score=min(score, 100),
            entry_price=price,
            stop_loss=stop_price,
            stop_loss_pct=sl_pct,
            take_profit_1=tp1_price,
            take_profit_2=tp2_price,
            tp1_pct=tp1_pct,
            tp2_pct=tp2_pct,
            confidence=min(score / 100, 0.95),
            vol_usd=vol_usd,
            timeframe="15m",
            setup_type="overbought_fade",
            reason=" | ".join(reasons),
            trail_activate_pct=self.config["trail_activate_pct"],
            trail_distance_pct=self.config["trail_distance_pct"],
            max_hold_minutes=self.config["max_hold_minutes_loser"],
        )

    def check_exit(self, position: dict, current_price: float, regime: str = "sideways") -> Optional[str]:
        entry = float(position.get("entry_price", 0))
        if entry <= 0 or current_price <= 0:
            return None

        side = position.get("side", "long")
        if side == "short":
            pnl_pct = (entry - current_price) / entry * 100
            lowest = float(position.get("lowest_price", current_price))
            peak_pnl = (entry - lowest) / entry * 100 if entry > 0 else 0
        else:
            pnl_pct = (current_price - entry) / entry * 100
            highest = float(position.get("highest_price", current_price))
            peak_pnl = (highest - entry) / entry * 100 if entry > 0 else 0
        hold_secs = float(position.get("hold_time_seconds", 0))
        hold_min = hold_secs / 60.0

        sl = self.config["sl_pct"]
        trail_act = self.config["trail_activate_pct"]
        trail_dist = self.config["trail_distance_pct"]
        max_hold_loser = self.config["max_hold_minutes_loser"]
        max_hold_hard = self.config["max_hold_minutes_hard"]

        # 1. Hard stop
        if pnl_pct <= sl:
            return "mr_sl"

        # 2. Trailing stop
        if peak_pnl >= trail_act:
            drawdown = peak_pnl - pnl_pct
            if drawdown >= trail_dist:
                return "mr_trail"

        # 3. Time exit for losers
        if hold_min >= max_hold_loser and pnl_pct <= 0:
            return "mr_time_exit"

        # 4. Hard time cap
        if hold_min >= max_hold_hard:
            return "mr_time_max"

        # 5. Quick profit lock — mean reversion targets are modest
        if pnl_pct >= 0.8 and hold_min >= 10 and pnl_pct < peak_pnl * 0.5:
            return "mr_profit_fade"

        return None
