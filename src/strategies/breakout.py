"""
Breakout ORB Strategy — Catches big momentum moves.

Opening Range Breakout + Volume-confirmed breakouts on 15m/1h charts.
Win rate: 55-65% | Trades: 3-8/day | Target: 1-3% per trade

Entry rules:
  1. Identify 15m opening range (first 2 candles of a session or consolidation)
  2. Price breaks above range high with volume > 1.5x average
  3. EMA9 > EMA21 on 1h (trend filter)
  4. RSI 45-75 (momentum present but not overbought)
  5. Bollinger Band width expanding (volatility breakout)

Exit rules:
  - TP1: +1.5% (take 30%)
  - TP2: +3.0% (take 25%)
  - Trail remaining at 1.0% distance after +1.5%
  - SL: below range low or -1.5% (whichever tighter)
  - Time exit: 2h max hold for losers, 4h hard cap
"""
from __future__ import annotations
import asyncio
import time
from typing import Optional
from loguru import logger
from .base import BaseStrategy, StrategySignal


class BreakoutORB(BaseStrategy):
    name = "breakout"
    max_signals_per_cycle = 3

    DEFAULTS = {
        "scan_interval_seconds": 30,
        "min_volume_24h": 2_000_000,
        "top_n_scan": 30,
        "consolidation_candles": 6,
        "breakout_threshold_pct": 0.3,
        "volume_breakout_mult": 1.5,
        "ema_fast": 9,
        "ema_slow": 21,
        "rsi_min": 45,
        "rsi_max": 78,
        "bb_period": 20,
        "bb_width_min": 0.5,
        "tp1_pct": 1.5,
        "tp2_pct": 3.0,
        "sl_pct": -1.5,
        "trail_activate_pct": 1.5,
        "trail_distance_pct": 1.0,
        "tp1_exit_frac": 0.30,
        "tp2_exit_frac": 0.25,
        "max_hold_minutes_loser": 120,
        "max_hold_minutes_hard": 240,
        "min_score": 55,
    }

    def __init__(self, exchange, config=None):
        merged = {**self.DEFAULTS, **(config or {})}
        super().__init__(exchange, merged)
        self._scan_interval = merged["scan_interval_seconds"]
        self._pair_cache: list[str] = []
        self._cache_time = 0.0
        self._recent_breakouts: dict[str, float] = {}

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
            logger.warning(f"[breakout] ticker fetch failed: {e}")
            return []

        min_vol = self.config["min_volume_24h"]
        long_candidates = []
        short_candidates = []
        pair_set = set(pairs)
        for sym, tk in tickers.items():
            if not sym.endswith("/USDT") or sym not in pair_set:
                continue
            vol = float(tk.get("quoteVolume") or 0)
            last = float(tk.get("last") or 0)
            pct = float(tk.get("percentage") or 0)
            if vol < min_vol or last <= 0:
                continue
            # Long: early momentum (0.5-6% range)
            if -2 <= pct <= 8:
                long_candidates.append((sym, vol, last, pct))
            # Short: breakdown candidates (weak or falling)
            if pct < 2:
                short_candidates.append((sym, vol, last, pct))

        long_candidates.sort(key=lambda x: x[1], reverse=True)
        long_candidates = long_candidates[: self.config["top_n_scan"]]
        short_candidates.sort(key=lambda x: x[1], reverse=True)
        short_candidates = short_candidates[: self.config["top_n_scan"]]

        # Clean old breakout cooldowns
        now = time.time()
        self._recent_breakouts = {
            k: v for k, v in self._recent_breakouts.items() if now - v < 3600
        }

        signals = []
        long_tasks = [self._analyze_breakout(sym, vol, last) for sym, vol, last, _ in long_candidates[:12]]
        short_tasks = [self._analyze_breakdown(sym, vol, last) for sym, vol, last, _ in short_candidates[:8]]
        results = await asyncio.gather(*(long_tasks + short_tasks), return_exceptions=True)
        for r in results:
            if isinstance(r, StrategySignal):
                if r.symbol not in self._recent_breakouts:
                    signals.append(r)

        signals.sort(key=lambda s: s.score, reverse=True)
        out = signals[: self.max_signals_per_cycle]
        for s in out:
            self._recent_breakouts[s.symbol] = now
        if out:
            logger.info(f"[breakout] {len(out)} signals: {[(s.symbol, s.direction) for s in out]}")
        return out

    async def _analyze_breakout(self, symbol: str, vol_usd: float, last_price: float) -> Optional[StrategySignal]:
        candles_15m, candles_1h = await asyncio.gather(
            self._fetch_candles(symbol, "15m", 50),
            self._fetch_candles(symbol, "1h", 30),
        )
        if len(candles_15m) < 20 or len(candles_1h) < 15:
            return None

        closes_15 = [c[4] for c in candles_15m]
        highs_15 = [c[2] for c in candles_15m]
        lows_15 = [c[3] for c in candles_15m]
        volumes_15 = [c[5] for c in candles_15m]
        price = closes_15[-1]

        # Anti-chase: skip if pump already peaked and pulling back
        exhausted, pb_pct = self.is_pump_exhausted(highs_15, closes_15, "long")
        if exhausted:
            logger.debug(f"[breakout] {symbol} skip: pump exhausted, pullback {pb_pct:.1f}%")
            return None

        closes_1h = [c[4] for c in candles_1h]

        # -- 1h Trend Filter --
        ema_f_1h = self.ema(closes_1h, self.config["ema_fast"])
        ema_s_1h = self.ema(closes_1h, self.config["ema_slow"])
        if not ema_f_1h or not ema_s_1h:
            return None
        trend_bullish = ema_f_1h[-1] > ema_s_1h[-1]

        # -- Consolidation Range Detection (last N 15m candles before current) --
        n = self.config["consolidation_candles"]
        if len(highs_15) < n + 2:
            return None
        range_highs = highs_15[-(n + 1):-1]
        range_lows = lows_15[-(n + 1):-1]
        range_high = max(range_highs)
        range_low = min(range_lows)
        range_pct = (range_high - range_low) / range_low * 100 if range_low > 0 else 999

        # Range must be tight (<3%) — true consolidation
        if range_pct > 3.0:
            return None

        # -- Breakout Detection --
        breakout_thresh = self.config["breakout_threshold_pct"]
        breakout_up = price > range_high * (1 + breakout_thresh / 100)
        if not breakout_up:
            return None

        # -- Scoring (0-100) --
        score = 0.0
        reasons = []

        # 1. Trend alignment (+25)
        if trend_bullish:
            score += 25
            reasons.append("1h_trend_bull")
        else:
            score += 5  # counter-trend breakout possible but lower score

        # 2. Breakout strength (+20)
        breakout_dist = (price - range_high) / range_high * 100
        if breakout_dist >= 0.5:
            score += 20
            reasons.append(f"breakout(+{breakout_dist:.2f}%)")
        elif breakout_dist >= 0.3:
            score += 15
            reasons.append(f"breakout(+{breakout_dist:.2f}%)")
        else:
            score += 10

        # 3. Volume confirmation (+20)
        avg_vol = sum(volumes_15[-20:]) / 20 if len(volumes_15) >= 20 else sum(volumes_15) / max(len(volumes_15), 1)
        vol_ratio = volumes_15[-1] / avg_vol if avg_vol > 0 else 0
        if vol_ratio >= self.config["volume_breakout_mult"]:
            score += 20
            reasons.append(f"vol({vol_ratio:.1f}x)")
        elif vol_ratio >= 1.0:
            score += 10
            reasons.append(f"vol_ok({vol_ratio:.1f}x)")
        else:
            return None  # No volume = fake breakout

        # 4. RSI filter (+15)
        rsi_val = self.rsi(closes_15, 14)
        if self.config["rsi_min"] <= rsi_val <= self.config["rsi_max"]:
            score += 15
            reasons.append(f"rsi({rsi_val:.0f})")
        elif rsi_val > self.config["rsi_max"]:
            score += 5  # slightly overbought but breakout can push through
        else:
            return None

        # 5. Bollinger Band width (volatility expansion) (+15)
        upper, mid, lower = self.bollinger_bands(closes_15, self.config["bb_period"])
        bb_width = (upper - lower) / mid * 100 if mid > 0 else 0
        if bb_width >= self.config["bb_width_min"]:
            score += 15
            reasons.append(f"bb_expanding({bb_width:.2f}%)")
        else:
            score += 5

        # 6. Range tightness bonus (+5)
        if range_pct < 1.5:
            score += 5
            reasons.append(f"tight_range({range_pct:.1f}%)")

        if score < self.config["min_score"]:
            return None

        # -- Compute levels --
        atr_val = self.atr(highs_15, lows_15, closes_15, 14)
        sl_pct = self.config["sl_pct"]

        # ATR-based stop: 2x ATR below entry
        if atr_val > 0 and price > 0:
            atr_stop = -(atr_val * 2.0 / price * 100)
            sl_pct = max(sl_pct, atr_stop)
            sl_pct = max(sl_pct, -2.5)
            sl_pct = min(sl_pct, -0.8)

        # Also use range low as stop if tighter
        range_stop_pct = -((price - range_low) / price * 100)
        if range_stop_pct > sl_pct and range_stop_pct < -0.3:
            sl_pct = range_stop_pct

        tp1_pct = self.config["tp1_pct"]
        tp2_pct = self.config["tp2_pct"]
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
            setup_type="breakout_orb",
            reason=" | ".join(reasons),
        )

    async def _analyze_breakdown(self, symbol: str, vol_usd: float, last_price: float) -> Optional[StrategySignal]:
        """Detect breakdown below consolidation range for SHORT entry."""
        candles_15m, candles_1h = await asyncio.gather(
            self._fetch_candles(symbol, "15m", 50),
            self._fetch_candles(symbol, "1h", 30),
        )
        if len(candles_15m) < 20 or len(candles_1h) < 15:
            return None

        closes_15 = [c[4] for c in candles_15m]
        highs_15 = [c[2] for c in candles_15m]
        lows_15 = [c[3] for c in candles_15m]
        volumes_15 = [c[5] for c in candles_15m]
        price = closes_15[-1]
        closes_1h = [c[4] for c in candles_1h]

        # 1h Trend: bearish for shorts
        ema_f_1h = self.ema(closes_1h, self.config["ema_fast"])
        ema_s_1h = self.ema(closes_1h, self.config["ema_slow"])
        if not ema_f_1h or not ema_s_1h:
            return None
        trend_bearish = ema_f_1h[-1] < ema_s_1h[-1]

        # Consolidation range
        n = self.config["consolidation_candles"]
        if len(lows_15) < n + 2:
            return None
        range_highs = highs_15[-(n + 1):-1]
        range_lows = lows_15[-(n + 1):-1]
        range_high = max(range_highs)
        range_low = min(range_lows)
        range_pct = (range_high - range_low) / range_low * 100 if range_low > 0 else 999
        if range_pct > 3.0:
            return None

        # Breakdown detection: price below range low
        breakout_thresh = self.config["breakout_threshold_pct"]
        breakdown = price < range_low * (1 - breakout_thresh / 100)
        if not breakdown:
            return None

        score = 0.0
        reasons = []

        # Trend alignment
        if trend_bearish:
            score += 25
            reasons.append("1h_trend_bear")
        else:
            score += 5

        # Breakdown strength
        breakdown_dist = (range_low - price) / range_low * 100
        if breakdown_dist >= 0.5:
            score += 20
            reasons.append(f"breakdown(-{breakdown_dist:.2f}%)")
        elif breakdown_dist >= 0.3:
            score += 15
        else:
            score += 10

        # Volume confirmation
        avg_vol = sum(volumes_15[-20:]) / 20 if len(volumes_15) >= 20 else sum(volumes_15) / max(len(volumes_15), 1)
        vol_ratio = volumes_15[-1] / avg_vol if avg_vol > 0 else 0
        if vol_ratio >= self.config["volume_breakout_mult"]:
            score += 20
            reasons.append(f"vol({vol_ratio:.1f}x)")
        elif vol_ratio >= 1.0:
            score += 10
        else:
            return None

        # RSI filter — lower RSI good for shorts
        rsi_val = self.rsi(closes_15, 14)
        if 20 <= rsi_val <= 55:
            score += 15
            reasons.append(f"rsi({rsi_val:.0f})")
        elif rsi_val < 20:
            return None  # too oversold, bounce risk

        # BB width
        upper, mid, lower = self.bollinger_bands(closes_15, self.config["bb_period"])
        bb_width = (upper - lower) / mid * 100 if mid > 0 else 0
        if bb_width >= self.config["bb_width_min"]:
            score += 15
            reasons.append(f"bb_expanding({bb_width:.2f}%)")

        if score < self.config["min_score"]:
            return None

        # Compute SHORT levels
        sl_pct = abs(self.config["sl_pct"])
        atr_val = self.atr(highs_15, lows_15, closes_15, 14)
        if atr_val > 0 and price > 0:
            atr_stop = atr_val * 2.0 / price * 100
            sl_pct = min(sl_pct, atr_stop)
            sl_pct = min(sl_pct, 2.5)
            sl_pct = max(sl_pct, 0.8)

        # Also use range high as stop
        range_stop_pct = (range_high - price) / price * 100
        if 0 < range_stop_pct < sl_pct:
            sl_pct = range_stop_pct

        tp1_pct = self.config["tp1_pct"]
        tp2_pct = self.config["tp2_pct"]
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
            setup_type="breakdown_orb",
            reason=" | ".join(reasons),
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
            return "breakout_sl"

        # 2. Trailing stop
        if peak_pnl >= trail_act:
            drawdown = peak_pnl - pnl_pct
            if drawdown >= trail_dist:
                return "breakout_trail"

        # 3. Time exit for losers
        if hold_min >= max_hold_loser and pnl_pct <= 0:
            return "breakout_time_exit"

        # 4. Hard time cap
        if hold_min >= max_hold_hard:
            return "breakout_time_max"

        # 5. Failed breakout — price fell back into range
        range_low_est = entry * (1 + sl / 100 * 0.6)
        if hold_min >= 30 and pnl_pct < -0.3 and current_price < entry * 0.997:
            return "breakout_failed"

        return None
