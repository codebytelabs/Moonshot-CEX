"""
Bollinger Band Squeeze Volatility Breakout Strategy.

Detects Bollinger Band squeeze (BB inside Keltner Channel) then enters
on expansion. Catches explosive moves from consolidation periods.
- WR: 50-60%, R:R: 2-3:1, Sharpe: 1.1-1.6
- Best: Post-consolidation volatility expansion. Worst: Sustained trends.

Detection:
  Squeeze: BB(20,2) width < KC(20,1.5×ATR) width
  Entry: BB expansion + directional momentum (EMA slope + volume)
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from loguru import logger

from .base import BaseStrategy, StrategySignal


class BBSqueezeStrategy(BaseStrategy):
    name = "bb_squeeze"
    max_signals_per_cycle = 3

    # ── Parameters ───────────────────────────────────────────────────────────
    BB_PERIOD = 20
    BB_STD = 2.0
    KC_PERIOD = 20
    KC_ATR_MULT = 1.5           
    ATR_SL_MULT = 1.5           
    ATR_TP_MULT = 2.5           
    ATR_TRAIL_MULT = 1.0        # Trailing distance = 1.0x ATR
    MAX_SL_PCT = -5.0           
    TRAIL_ACTIVATE_PCT = 2.0     
    TRAIL_DISTANCE_PCT = 1.5
    MAX_HOLD_MINUTES = 300      # 5h — squeeze breakouts can run
    SQUEEZE_MIN_BARS = 3        # Require at least 3 bars of squeeze

    async def analyze(
        self, symbol_data: dict[str, dict[str, np.ndarray]], regime: str = "sideways"
    ) -> list[StrategySignal]:
        signals = []
        for symbol, tf_data in symbol_data.items():
            sig = self._analyze_one(symbol, tf_data, regime)
            if sig:
                signals.append(sig)
        signals.sort(key=lambda s: s.score, reverse=True)
        return signals[: self.max_signals_per_cycle]

    def _analyze_one(
        self, symbol: str, tf_data: dict[str, np.ndarray], regime: str
    ) -> Optional[StrategySignal]:
        data_1h = tf_data.get("1h")
        data_4h = tf_data.get("4h")
        if data_1h is None or len(data_1h) < 30:
            return None

        closes_1h = data_1h[:, 4].tolist()
        highs_1h = data_1h[:, 2].tolist()
        lows_1h = data_1h[:, 3].tolist()
        volumes_1h = data_1h[:, 5].tolist()

        price = closes_1h[-1]

        # ── Detect BB Squeeze ────────────────────────────────────────────────
        # Squeeze = BB is INSIDE Keltner Channel (low volatility period)
        squeeze_state, squeeze_bars = self._detect_squeeze(
            highs_1h, lows_1h, closes_1h
        )

        # We want: squeeze was active recently AND now expanding
        # "Recently" = squeeze ended within last 5 bars
        if squeeze_bars < self.SQUEEZE_MIN_BARS and squeeze_state:
            return None  # still squeezing, not yet breaking out

        # Check if squeeze just released (was squeezing, now expanding)
        just_released = not squeeze_state and squeeze_bars >= self.SQUEEZE_MIN_BARS
        if not just_released:
            # Also catch early squeeze where BB is about to break out
            # BB width expanding from very tight
            bb_widths = self._compute_bb_width_series(closes_1h)
            if len(bb_widths) >= 3:
                expanding = bb_widths[-1] > bb_widths[-2] > bb_widths[-3]
                tight = bb_widths[-3] < 0.03  # very tight band
                if not (expanding and tight):
                    return None
            else:
                return None

        # ── Direction: which way is the breakout going? ──────────────────────
        # Use EMA12 slope + last 3 candles direction
        ema12 = self.ema(closes_1h, 12)
        if not ema12 or len(ema12) < 3:
            return None

        ema_slope = (ema12[-1] - ema12[-3]) / ema12[-3] * 100 if ema12[-3] > 0 else 0

        # Candle direction
        green_count = sum(1 for i in range(-3, 0) if closes_1h[i] > closes_1h[i - 1])
        red_count = 3 - green_count

        direction = None
        if ema_slope > 0.1 and green_count >= 2:
            direction = "long"
        elif ema_slope < -0.1 and red_count >= 2:
            direction = "short"

        if direction is None:
            return None

        # ── 4H trend bias ────────────────────────────────────────────────────
        # In bull regime, prefer longs. In bear, prefer shorts.
        if data_4h is not None and len(data_4h) >= 55:
            closes_4h = data_4h[:, 4].tolist()
            ema50_4h = self.ema(closes_4h, 50)
            if ema50_4h:
                if direction == "long" and closes_4h[-1] < ema50_4h[-1] * 0.96:
                    # Deep below 4H trend — risky long
                    if regime != "choppy":  # choppy = anything goes
                        return None
                elif direction == "short" and closes_4h[-1] > ema50_4h[-1] * 1.04:
                    if regime != "choppy":
                        return None

        # ── Volume confirmation ──────────────────────────────────────────────
        avg_vol = np.mean(volumes_1h[-20:]) if len(volumes_1h) >= 20 else np.mean(volumes_1h)
        vol_ratio = volumes_1h[-1] / avg_vol if avg_vol > 0 else 1.0
        # Squeeze breakouts SHOULD have volume expansion
        if vol_ratio < 1.0:
            return None  # no volume on expansion = likely false breakout

        # ── RSI filter ───────────────────────────────────────────────────────
        rsi_val = self.rsi(closes_1h, 14)
        if direction == "long" and rsi_val > 80:
            return None
        if direction == "short" and rsi_val < 20:
            return None

        # ── ATR-based stops ──────────────────────────────────────────────────
        atr_val = self.atr(highs_1h, lows_1h, closes_1h, 14)
        if atr_val <= 0:
            return None

        if direction == "long":
            sl = price - atr_val * self.ATR_SL_MULT
            tp1 = price + atr_val * self.ATR_TP_MULT
            tp2 = price + atr_val * self.ATR_TP_MULT * 1.5
            sl_pct = -abs((price - sl) / price * 100)
        else:
            sl = price + atr_val * self.ATR_SL_MULT
            tp1 = price - atr_val * self.ATR_TP_MULT
            tp2 = price - atr_val * self.ATR_TP_MULT * 1.5
            sl_pct = -abs((sl - price) / price * 100)

        # ── Hard cap SL at MAX_SL_PCT ──────────────────────────────────────
        # v7.8.1: tighter cap in bear/choppy. Squeeze breakouts in hostile
        # regimes have a higher false-breakout rate — cut the max loss per
        # signal before it becomes a portfolio-level drain.
        _max_sl = -3.5 if regime in ("bear", "choppy") else self.MAX_SL_PCT
        if sl_pct < _max_sl:
            sl_pct = _max_sl
            if direction == "long":
                sl = price * (1 + sl_pct / 100)
            else:
                sl = price * (1 - sl_pct / 100)

        # ── Score ────────────────────────────────────────────────────────────
        score = 45.0

        # Squeeze duration bonus: longer squeeze = bigger breakout potential
        squeeze_bonus = min(15.0, (squeeze_bars - self.SQUEEZE_MIN_BARS) * 2)
        score += max(0, squeeze_bonus)

        # Volume expansion bonus
        vol_score = min(15.0, (vol_ratio - 1.0) * 10)
        score += max(0, vol_score)

        # EMA slope strength
        slope_score = min(10.0, abs(ema_slope) * 5)
        score += slope_score

        # RSI in expansion zone (not extreme)
        if direction == "long" and 45 <= rsi_val <= 70:
            score += 10.0
        elif direction == "short" and 30 <= rsi_val <= 55:
            score += 10.0

        # 4H alignment bonus
        if data_4h is not None and len(data_4h) >= 55:
            closes_4h = data_4h[:, 4].tolist()
            ema50_4h = self.ema(closes_4h, 50)
            if ema50_4h:
                if direction == "long" and closes_4h[-1] > ema50_4h[-1]:
                    score += 5.0
                elif direction == "short" and closes_4h[-1] < ema50_4h[-1]:
                    score += 5.0

        score = min(100.0, score)

        return StrategySignal(
            symbol=symbol,
            strategy=self.name,
            direction=direction,
            score=score,
            entry_price=price,
            stop_loss=sl,
            stop_loss_pct=sl_pct,
            take_profit_1=tp1,
            take_profit_2=tp2,
            tp1_pct=abs((tp1 - price) / price * 100),
            tp2_pct=abs((tp2 - price) / price * 100),
            confidence=score / 100.0,
            setup_type="bb_squeeze_breakout",
            reason=f"BB squeeze {direction} bars={squeeze_bars} vol={vol_ratio:.1f}x slope={ema_slope:+.2f}% RSI={rsi_val:.0f}",
            timeframe="1h",
            # v7.8.1: in bear/choppy, activate trailing sooner (lock in gains
            # faster) and cap hold at 150min (2.5h) — squeeze breakouts that
            # haven't paid off in 2.5h in a hostile regime won't.
            trail_activate_pct=1.5 if regime in ("bear", "choppy") else self.TRAIL_ACTIVATE_PCT,
            trail_distance_pct=self.TRAIL_DISTANCE_PCT,
            trail_distance_price=atr_val * self.ATR_TRAIL_MULT,
            max_hold_minutes=150 if regime in ("bear", "choppy") else self.MAX_HOLD_MINUTES,
        )

    def _detect_squeeze(
        self, highs: list, lows: list, closes: list
    ) -> tuple[bool, int]:
        """
        Detect BB squeeze: BB inside Keltner Channel.
        Returns (currently_squeezing, bars_in_squeeze).
        """
        if len(closes) < max(self.BB_PERIOD, self.KC_PERIOD) + 5:
            return False, 0

        squeeze_count = 0
        currently_squeezing = False

        # Check last 20 bars for squeeze state
        check_range = min(20, len(closes) - max(self.BB_PERIOD, self.KC_PERIOD))
        for offset in range(check_range, 0, -1):
            end_idx = len(closes) - offset + 1
            c_slice = closes[:end_idx]
            h_slice = highs[:end_idx]
            l_slice = lows[:end_idx]

            if len(c_slice) < self.BB_PERIOD:
                continue

            # BB
            bb_upper, bb_mid, bb_lower = self.bollinger_bands(
                c_slice, self.BB_PERIOD, self.BB_STD
            )
            # KC
            kc_mid = bb_mid  # same SMA base
            atr_val = self.atr(h_slice, l_slice, c_slice, self.KC_PERIOD)
            kc_upper = kc_mid + self.KC_ATR_MULT * atr_val
            kc_lower = kc_mid - self.KC_ATR_MULT * atr_val

            is_squeeze = bb_lower > kc_lower and bb_upper < kc_upper
            if offset == 1:
                currently_squeezing = is_squeeze

            if is_squeeze:
                squeeze_count += 1
            elif offset > 1:
                # Reset if squeeze broke before reaching current bar
                squeeze_count = 0

        return currently_squeezing, squeeze_count

    def _compute_bb_width_series(self, closes: list) -> list[float]:
        """Compute BB width for last N bars."""
        widths = []
        for i in range(min(10, len(closes) - self.BB_PERIOD), 0, -1):
            end = len(closes) - i + 1
            c_slice = closes[:end]
            if len(c_slice) < self.BB_PERIOD:
                continue
            bb_u, bb_m, bb_l = self.bollinger_bands(c_slice, self.BB_PERIOD, self.BB_STD)
            if bb_m > 0:
                widths.append((bb_u - bb_l) / bb_m)
        return widths

    async def scan(self, regime: str = "sideways") -> list[StrategySignal]:
        return []

    def check_exit(self, position: dict, current_price: float, regime: str = "sideways") -> Optional[str]:
        entry = float(position.get("entry_price", 0))
        if entry <= 0 or current_price <= 0:
            return None
        direction = position.get("side", "long")
        pnl_pct = ((current_price - entry) / entry * 100) if direction == "long" \
            else ((entry - current_price) / entry * 100)
        highest = float(position.get("highest_price", current_price))
        peak_pnl = ((highest - entry) / entry * 100) if direction == "long" \
            else ((entry - highest) / entry * 100)
        hold_h = float(position.get("hold_time_hours", 0))

        # Trailing stop
        if peak_pnl >= self.TRAIL_ACTIVATE_PCT:
            drawdown = peak_pnl - pnl_pct
            if drawdown >= self.TRAIL_DISTANCE_PCT:
                return "bb_squeeze_trail"

        # Time exit
        if hold_h >= (self.MAX_HOLD_MINUTES / 60) and pnl_pct <= 0:
            return "bb_squeeze_time"

        return None

    def check_falsification(self, position: dict, tf_data: dict[str, list]) -> tuple[bool, str]:
        """Falsify if the breakout completely fails and collapses across the Middle Bollinger Band."""
        data_1h = tf_data.get("1h")
        if data_1h is None or len(data_1h) < self.BB_PERIOD:
            return False, ""
            
        closes = [c[4] for c in data_1h[-self.BB_PERIOD:]]
        current_price = closes[-1]
        
        try:
            _, bb_mid, _ = self.bollinger_bands(closes, self.BB_PERIOD, self.BB_STD)
        except Exception:
            return False, ""
            
        if not bb_mid:
            return False, ""
            
        direction = position.get("side", "long")
        # Breakout fakeout: longs falling significantly below the midline (0.5% buffer)
        if direction == "long" and current_price < bb_mid * 0.995:
            return True, "thesis_falsified_squeeze_fakeout_down"
        elif direction == "short" and current_price > bb_mid * 1.005:
            return True, "thesis_falsified_squeeze_fakeout_up"
            
        return False, ""
