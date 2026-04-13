"""
VWAP + Volume Breakout Momentum Strategy — Catch early breakouts with volume.

Enters when price breaks above/below VWAP with 1.5x+ volume confirmation.
Key insight: enters EARLY (before the move completes) by requiring volume.
- WR: 45-55%, R:R: 2:1+, Sharpe: 1.0-1.4
- Best: Bull transitions, momentum surges. Worst: Low-volume chop.

Multi-timeframe:
  4H: trend bias (EMA50 position)
  1H: VWAP calculation + volume breakout detection
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from loguru import logger

from .base import BaseStrategy, StrategySignal


class VWAPMomentumStrategy(BaseStrategy):
    name = "vwap_momentum"
    max_signals_per_cycle = 3

    # ── Parameters ───────────────────────────────────────────────────────────
    VOL_THRESHOLD = 1.5         # volume must be 1.5x average
    VWAP_BUFFER_PCT = 0.3       # price must be 0.3%+ above/below VWAP
    ATR_SL_MULT = 2.0           # stop loss = 2 × ATR (tighter for momentum)
    ATR_TP_MULT = 4.0           # take profit = 4 × ATR (2:1 R:R)
    TRAIL_ACTIVATE_PCT = 1.5    # activate trailing early — catch momentum
    TRAIL_DISTANCE_PCT = 1.2    # tight trail to lock in gains
    MAX_HOLD_MINUTES = 180      # 3h max — momentum trades are fast

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

        highs_1h = data_1h[:, 2].tolist()
        lows_1h = data_1h[:, 3].tolist()
        closes_1h = data_1h[:, 4].tolist()
        volumes_1h = data_1h[:, 5].tolist()

        price = closes_1h[-1]

        # ── VWAP calculation ─────────────────────────────────────────────────
        # Use last 24 bars (24h on 1H) as VWAP period
        vwap_len = min(24, len(closes_1h))
        h = highs_1h[-vwap_len:]
        l = lows_1h[-vwap_len:]
        c = closes_1h[-vwap_len:]
        v = volumes_1h[-vwap_len:]

        cum_tp_vol = sum((h[i] + l[i] + c[i]) / 3 * v[i] for i in range(len(c)))
        cum_vol = sum(v)
        vwap_val = cum_tp_vol / cum_vol if cum_vol > 0 else price

        # ── Volume breakout detection ────────────────────────────────────────
        avg_vol = np.mean(volumes_1h[-20:]) if len(volumes_1h) >= 20 else np.mean(volumes_1h)
        current_vol = volumes_1h[-1]
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0

        if vol_ratio < self.VOL_THRESHOLD:
            return None  # no volume = no breakout

        # ── Direction from VWAP position ─────────────────────────────────────
        vwap_distance_pct = (price - vwap_val) / vwap_val * 100 if vwap_val > 0 else 0

        direction = None
        if vwap_distance_pct >= self.VWAP_BUFFER_PCT:
            direction = "long"   # price breaking above VWAP with volume
        elif vwap_distance_pct <= -self.VWAP_BUFFER_PCT:
            direction = "short"  # price breaking below VWAP with volume

        if direction is None:
            return None

        # ── 4H trend alignment ───────────────────────────────────────────────
        trend_aligned = True
        if data_4h is not None and len(data_4h) >= 55:
            closes_4h = data_4h[:, 4].tolist()
            ema50_4h = self.ema(closes_4h, 50)
            if ema50_4h:
                if direction == "long" and closes_4h[-1] < ema50_4h[-1] * 0.97:
                    trend_aligned = False  # going long below major 4H trend
                elif direction == "short" and closes_4h[-1] > ema50_4h[-1] * 1.03:
                    trend_aligned = False  # going short above major 4H trend

        if not trend_aligned and regime not in ("bear", "choppy"):
            return None  # only override trend in volatile regimes

        # ── Momentum confirmation: recent price action ───────────────────────
        # Price should be making new highs (longs) or new lows (shorts) in last 6 bars
        if direction == "long":
            recent_high = max(highs_1h[-6:]) if len(highs_1h) >= 6 else price
            if price < recent_high * 0.985:
                return None  # already pulled back from high — momentum dead
        else:
            recent_low = min(lows_1h[-6:]) if len(lows_1h) >= 6 else price
            if price > recent_low * 1.015:
                return None  # already bounced from low

        # ── RSI filter ───────────────────────────────────────────────────────
        rsi_val = self.rsi(closes_1h, 14)
        if direction == "long" and rsi_val > 80:
            return None
        if direction == "short" and rsi_val < 20:
            return None

        # ── MACD momentum confirmation ───────────────────────────────────────
        macd_line, sig_line, hist = self.macd(closes_1h)
        if direction == "long" and hist < 0:
            return None  # MACD bearish — don't go long
        if direction == "short" and hist > 0:
            return None  # MACD bullish — don't go short

        # ── ATR-based stops ──────────────────────────────────────────────────
        atr_val = self.atr(highs_1h, lows_1h, closes_1h, 14)
        if atr_val <= 0:
            return None

        if direction == "long":
            sl = max(price - atr_val * self.ATR_SL_MULT, vwap_val * 0.995)
            tp1 = price + atr_val * self.ATR_TP_MULT
            tp2 = price + atr_val * self.ATR_TP_MULT * 1.5
            sl_pct = -abs((price - sl) / price * 100)
        else:
            sl = min(price + atr_val * self.ATR_SL_MULT, vwap_val * 1.005)
            tp1 = price - atr_val * self.ATR_TP_MULT
            tp2 = price - atr_val * self.ATR_TP_MULT * 1.5
            sl_pct = -abs((sl - price) / price * 100)

        # ── Score ────────────────────────────────────────────────────────────
        score = 40.0

        # Volume strength (1.5x-3x maps to 0-20 pts)
        vol_score = min(20.0, (vol_ratio - self.VOL_THRESHOLD) / 1.5 * 20)
        score += vol_score

        # VWAP distance (farther from VWAP = stronger breakout)
        vwap_score = min(15.0, abs(vwap_distance_pct) * 5)
        score += vwap_score

        # MACD histogram strength
        if direction == "long" and hist > 0:
            score += min(10.0, hist / atr_val * 100) if atr_val > 0 else 0
        elif direction == "short" and hist < 0:
            score += min(10.0, abs(hist) / atr_val * 100) if atr_val > 0 else 0

        # 4H trend alignment bonus
        if trend_aligned:
            score += 10.0

        # RSI in momentum zone
        if direction == "long" and 50 <= rsi_val <= 72:
            score += 5.0
        elif direction == "short" and 28 <= rsi_val <= 50:
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
            setup_type="vwap_momentum_breakout",
            reason=f"VWAP breakout {direction} vol={vol_ratio:.1f}x VWAP_dist={vwap_distance_pct:+.1f}% RSI={rsi_val:.0f}",
            timeframe="1h",
            trail_activate_pct=self.TRAIL_ACTIVATE_PCT,
            trail_distance_pct=self.TRAIL_DISTANCE_PCT,
            max_hold_minutes=self.MAX_HOLD_MINUTES,
        )

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

        # Tight trailing stop — lock in momentum gains
        if peak_pnl >= self.TRAIL_ACTIVATE_PCT:
            drawdown = peak_pnl - pnl_pct
            if drawdown >= self.TRAIL_DISTANCE_PCT:
                return "vwap_momentum_trail"

        # Quick time exit — momentum is fast
        if hold_h >= (self.MAX_HOLD_MINUTES / 60) and pnl_pct <= 0:
            return "vwap_momentum_time"

        return None
