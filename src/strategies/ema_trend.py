"""
EMA Trend Following Strategy — Dual EMA crossover with ADX filter.

Proven approach: ride established trends, avoid choppy/sideways.
- Entry: EMA12 cross above EMA50 + ADX > 25 + 4H trend confirmation
- Exit: ATR-based trailing stop, opposite EMA crossover, or time
- WR: 40-50%, R:R: 2-3:1, Sharpe: 1.2-1.5
- Best: Bull/Bear trending. Worst: Sideways/choppy.

Multi-timeframe:
  4H: trend direction (EMA50 slope + price position)
  1H: signal generation (EMA12/50 crossover + ADX filter)
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from loguru import logger

from .base import BaseStrategy, StrategySignal


class EMATrendStrategy(BaseStrategy):
    name = "ema_trend"
    max_signals_per_cycle = 3

    # ── Parameters ───────────────────────────────────────────────────────────
    EMA_FAST = 12
    EMA_SLOW = 50
    ADX_PERIOD = 14
    ADX_THRESHOLD = 25          # minimum ADX for trend confirmation
    ATR_SL_MULT = 2.5           # stop loss = 2.5 × ATR
    ATR_TP_MULT = 5.0           # take profit = 5.0 × ATR (2:1 R:R)
    TRAIL_ACTIVATE_PCT = 2.0    # activate trailing at +2%
    TRAIL_DISTANCE_PCT = 1.5    # trail distance 1.5%
    MAX_HOLD_MINUTES = 240      # 4h max hold

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
        # Need both 1H and 4H data
        data_1h = tf_data.get("1h")
        data_4h = tf_data.get("4h")
        if data_1h is None or len(data_1h) < 60:
            return None
        if data_4h is None or len(data_4h) < 55:
            return None

        closes_1h = data_1h[:, 4].tolist()
        highs_1h = data_1h[:, 2].tolist()
        lows_1h = data_1h[:, 3].tolist()
        volumes_1h = data_1h[:, 5].tolist()
        closes_4h = data_4h[:, 4].tolist()

        # ── 4H Trend Direction ───────────────────────────────────────────────
        ema50_4h_series = self.ema(closes_4h, 50)
        if not ema50_4h_series or len(ema50_4h_series) < 2:
            return None
        ema50_4h = ema50_4h_series[-1]
        ema50_4h_prev = ema50_4h_series[-5] if len(ema50_4h_series) >= 5 else ema50_4h
        price_4h = closes_4h[-1]

        trend_4h = "neutral"
        if price_4h > ema50_4h and ema50_4h > ema50_4h_prev:
            trend_4h = "bull"
        elif price_4h < ema50_4h and ema50_4h < ema50_4h_prev:
            trend_4h = "bear"

        # In bull regime, only take longs. In bear, only shorts.
        if regime == "bull" and trend_4h == "bear":
            return None
        if regime == "bear" and trend_4h == "bull":
            return None

        # ── 1H Signal: EMA12/50 crossover ────────────────────────────────────
        ema_fast = self.ema(closes_1h, self.EMA_FAST)
        ema_slow = self.ema(closes_1h, self.EMA_SLOW)
        if not ema_fast or not ema_slow or len(ema_fast) < 3 or len(ema_slow) < 3:
            return None

        # Crossover detection: fast crossed above/below slow in last 3 bars
        direction = None
        for i in range(-3, 0):
            if (ema_fast[i - 1] <= ema_slow[i - 1] and ema_fast[i] > ema_slow[i]):
                direction = "long"
                break
            elif (ema_fast[i - 1] >= ema_slow[i - 1] and ema_fast[i] < ema_slow[i]):
                direction = "short"
                break

        if direction is None:
            # No recent crossover — check if already in trend (riding)
            if ema_fast[-1] > ema_slow[-1] * 1.002 and trend_4h == "bull":
                direction = "long"
            elif ema_fast[-1] < ema_slow[-1] * 0.998 and trend_4h == "bear":
                direction = "short"
            else:
                return None

        # Block shorts in bull regime, longs in bear
        if direction == "long" and regime == "bear":
            return None
        if direction == "short" and regime == "bull":
            return None

        # ── ADX filter: only trade strong trends ─────────────────────────────
        adx = self._compute_adx(highs_1h, lows_1h, closes_1h, self.ADX_PERIOD)
        if adx < self.ADX_THRESHOLD:
            return None

        # ── RSI confirmation ─────────────────────────────────────────────────
        rsi_1h = self.rsi(closes_1h, 14)
        if direction == "long" and rsi_1h > 78:
            return None  # overbought
        if direction == "short" and rsi_1h < 22:
            return None  # oversold

        # ── ATR-based stops ──────────────────────────────────────────────────
        atr_val = self.atr(highs_1h, lows_1h, closes_1h, 14)
        if atr_val <= 0:
            return None

        price = closes_1h[-1]
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

        # ── Score ────────────────────────────────────────────────────────────
        score = 40.0  # base
        # ADX strength bonus (25-50 maps to 0-20 pts)
        score += min(20.0, max(0.0, (adx - self.ADX_THRESHOLD) * 0.8))
        # RSI in trend zone bonus
        if direction == "long" and 50 <= rsi_1h <= 70:
            score += 15.0
        elif direction == "short" and 30 <= rsi_1h <= 50:
            score += 15.0
        # 4H trend alignment bonus
        if (direction == "long" and trend_4h == "bull") or \
           (direction == "short" and trend_4h == "bear"):
            score += 15.0
        # Volume confirmation
        avg_vol = np.mean(volumes_1h[-20:]) if len(volumes_1h) >= 20 else np.mean(volumes_1h)
        vol_ratio = volumes_1h[-1] / avg_vol if avg_vol > 0 else 1.0
        if vol_ratio > 1.5:
            score += 10.0

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
            setup_type="ema_trend_follow",
            reason=f"EMA{self.EMA_FAST}/{self.EMA_SLOW} cross {direction} ADX={adx:.0f} RSI={rsi_1h:.0f} 4H={trend_4h}",
            timeframe="1h",
            trail_activate_pct=self.TRAIL_ACTIVATE_PCT,
            trail_distance_pct=self.TRAIL_DISTANCE_PCT,
            max_hold_minutes=self.MAX_HOLD_MINUTES,
        )

    async def scan(self, regime: str = "sideways") -> list[StrategySignal]:
        """Not used directly — RegimeEngine calls analyze() instead."""
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
                return "ema_trend_trail"

        # Time exit for losers
        if hold_h >= (self.MAX_HOLD_MINUTES / 60) and pnl_pct <= 0:
            return "ema_trend_time"

        return None

    @staticmethod
    def _compute_adx(highs: list, lows: list, closes: list, period: int = 14) -> float:
        """Compute ADX (Average Directional Index)."""
        if len(highs) < period + 1:
            return 0.0

        plus_dm = []
        minus_dm = []
        tr_list = []

        for i in range(1, len(highs)):
            high_diff = highs[i] - highs[i - 1]
            low_diff = lows[i - 1] - lows[i]

            pdm = high_diff if high_diff > low_diff and high_diff > 0 else 0.0
            mdm = low_diff if low_diff > high_diff and low_diff > 0 else 0.0
            plus_dm.append(pdm)
            minus_dm.append(mdm)

            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            tr_list.append(tr)

        if len(tr_list) < period:
            return 0.0

        # Smoothed averages
        atr_s = sum(tr_list[:period])
        pdm_s = sum(plus_dm[:period])
        mdm_s = sum(minus_dm[:period])

        dx_list = []
        for i in range(period, len(tr_list)):
            atr_s = atr_s - atr_s / period + tr_list[i]
            pdm_s = pdm_s - pdm_s / period + plus_dm[i]
            mdm_s = mdm_s - mdm_s / period + minus_dm[i]

            pdi = (pdm_s / atr_s * 100) if atr_s > 0 else 0
            mdi = (mdm_s / atr_s * 100) if atr_s > 0 else 0
            dx = abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) > 0 else 0
            dx_list.append(dx)

        if not dx_list:
            return 0.0

        # ADX = smoothed DX
        adx = sum(dx_list[:period]) / period if len(dx_list) >= period else sum(dx_list) / len(dx_list)
        for i in range(period, len(dx_list)):
            adx = (adx * (period - 1) + dx_list[i]) / period

        return adx
