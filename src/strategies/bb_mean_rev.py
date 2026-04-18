"""
Bollinger Band Mean Reversion Strategy — Fade extremes in ranging markets.

Buys at lower BB + RSI oversold, sells at upper BB + RSI overbought.
ADX < 25 filter ensures we only trade in range-bound conditions.
- WR: 60-70%, R:R: 1-1.5:1, Sharpe: 0.8-1.1
- Best: Sideways/ranging. Worst: Strong trends.

Multi-timeframe:
  4H: confirm no strong trend (ADX < 25)
  1H: signal generation (BB touch + RSI extreme)
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from loguru import logger

from .base import BaseStrategy, StrategySignal


class BBMeanRevStrategy(BaseStrategy):
    name = "bb_mean_rev"
    max_signals_per_cycle = 3

    # ── Parameters ───────────────────────────────────────────────────────────
    BB_PERIOD = 20
    BB_STD = 2.0
    RSI_OVERSOLD = 30
    RSI_OVERBOUGHT = 70
    ADX_MAX = 25                # only trade when ADX < 25 (no trend)
    ATR_SL_MULT = 2.0           # tighter stops for mean rev
    ATR_TP_MULT = 2.5           # target middle BB (~1.25:1 R:R)
    ATR_TRAIL_MULT = 1.0  
    MAX_SL_PCT = -5.0           # hard cap — never risk more than 5%
    TRAIL_ACTIVATE_PCT = 1.5
    TRAIL_DISTANCE_PCT = 1.0
    MAX_HOLD_MINUTES = 180      # 3h max — mean rev trades are quick

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

        # ── ADX filter: MUST be low (no strong trend) ────────────────────────
        from .ema_trend import EMATrendStrategy
        adx = EMATrendStrategy._compute_adx(highs_1h, lows_1h, closes_1h, 14)
        if adx >= self.ADX_MAX:
            return None  # trending — mean rev will fail

        # ── 4H trend check: skip if 4H is strongly trending ─────────────────
        if data_4h is not None and len(data_4h) >= 55:
            closes_4h = data_4h[:, 4].tolist()
            highs_4h = data_4h[:, 2].tolist()
            lows_4h = data_4h[:, 3].tolist()
            adx_4h = EMATrendStrategy._compute_adx(highs_4h, lows_4h, closes_4h, 14)
            if adx_4h > 30:
                return None  # strong 4H trend — dangerous for mean rev

        # ── Bollinger Bands ──────────────────────────────────────────────────
        bb_upper, bb_mid, bb_lower = self.bollinger_bands(
            closes_1h, self.BB_PERIOD, self.BB_STD
        )
        price = closes_1h[-1]

        # ── RSI ──────────────────────────────────────────────────────────────
        rsi_val = self.rsi(closes_1h, 14)

        # ── Signal generation ────────────────────────────────────────────────
        direction = None

        # Long: price at/below lower BB + RSI oversold zone
        if price <= bb_lower * 1.005 and rsi_val <= self.RSI_OVERSOLD + 5:
            direction = "long"

        # Short: price at/above upper BB + RSI overbought zone
        elif price >= bb_upper * 0.995 and rsi_val >= self.RSI_OVERBOUGHT - 5:
            direction = "short"

        if direction is None:
            return None

        # ── Additional confirmation: price divergence from BB ────────────────
        # Stronger signal when price is deeper into BB extreme
        if direction == "long":
            bb_penetration = (bb_lower - price) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0
        else:
            bb_penetration = (price - bb_upper) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0

        # ── ATR-based stops ──────────────────────────────────────────────────
        atr_val = self.atr(highs_1h, lows_1h, closes_1h, 14)
        if atr_val <= 0:
            return None

        if direction == "long":
            sl = price - atr_val * self.ATR_SL_MULT
            tp1 = bb_mid  # target middle BB
            tp2 = bb_upper * 0.99  # near upper BB
            sl_pct = -abs((price - sl) / price * 100)
        else:
            sl = price + atr_val * self.ATR_SL_MULT
            tp1 = bb_mid
            tp2 = bb_lower * 1.01
            sl_pct = -abs((sl - price) / price * 100)

        # ── Hard cap SL at MAX_SL_PCT ──────────────────────────────────────
        if sl_pct < self.MAX_SL_PCT:
            sl_pct = self.MAX_SL_PCT
            if direction == "long":
                sl = price * (1 + sl_pct / 100)
            else:
                sl = price * (1 - sl_pct / 100)

        # ── Score ────────────────────────────────────────────────────────────
        score = 45.0  # base

        # RSI extremity bonus (deeper = stronger)
        if direction == "long":
            rsi_bonus = max(0, (self.RSI_OVERSOLD + 5 - rsi_val)) * 1.0
        else:
            rsi_bonus = max(0, (rsi_val - self.RSI_OVERBOUGHT + 5)) * 1.0
        score += min(20.0, rsi_bonus)

        # BB penetration bonus
        score += min(15.0, max(0, bb_penetration * 30))

        # Low ADX = cleaner range = better for mean rev
        adx_bonus = max(0, (self.ADX_MAX - adx)) * 0.5
        score += min(10.0, adx_bonus)

        # Volume dry-up confirmation (low volume = range intact)
        avg_vol = np.mean(volumes_1h[-20:]) if len(volumes_1h) >= 20 else np.mean(volumes_1h)
        vol_ratio = volumes_1h[-1] / avg_vol if avg_vol > 0 else 1.0
        if vol_ratio < 0.8:
            score += 5.0  # quiet = mean rev friendly

        # BB width check: narrow BB = tight range = good for mean rev
        bb_width = (bb_upper - bb_lower) / bb_mid if bb_mid > 0 else 0
        if bb_width < 0.04:
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
            setup_type="bb_mean_reversion",
            reason=f"BB mean rev {direction} RSI={rsi_val:.0f} ADX={adx:.0f} BBpen={bb_penetration:.2f}",
            timeframe="1h",
            trail_activate_pct=self.TRAIL_ACTIVATE_PCT,
            trail_distance_pct=self.TRAIL_DISTANCE_PCT,
            trail_distance_price=atr_val * self.ATR_TRAIL_MULT,
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

        # Mean rev: quick exits — trailing at lower threshold
        if peak_pnl >= self.TRAIL_ACTIVATE_PCT:
            drawdown = peak_pnl - pnl_pct
            if drawdown >= self.TRAIL_DISTANCE_PCT:
                return "bb_meanrev_trail"

        # Time exit: mean rev should resolve quickly
        if hold_h >= (self.MAX_HOLD_MINUTES / 60) and pnl_pct <= 0:
            return "bb_meanrev_time"

        return None
