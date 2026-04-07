"""
Base strategy interface for Moonshot-CEX multi-strategy engine.

Every strategy must implement:
  - scan()   → find candidate symbols
  - analyze() → score and filter candidates, produce StrategySignal list
  - exit_check() → per-tick exit logic for open positions

StrategySignal is the universal output format that the strategy manager
feeds into risk gating and execution.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger


@dataclass
class StrategySignal:
    """Universal trade signal emitted by any strategy."""
    symbol: str
    strategy: str                      # "scalper" | "breakout" | "mean_reversion"
    direction: str = "long"            # "long" | "short"
    score: float = 0.0                 # composite quality score 0-100
    entry_price: float = 0.0          # suggested entry (0 = market)
    stop_loss: float = 0.0            # absolute stop price
    stop_loss_pct: float = -2.0       # stop as % from entry
    take_profit_1: float = 0.0        # TP1 absolute
    take_profit_2: float = 0.0        # TP2 absolute
    tp1_pct: float = 1.0             # TP1 as % from entry
    tp2_pct: float = 3.0             # TP2 as % from entry
    confidence: float = 0.5           # 0-1 conviction
    leverage: int = 1                 # suggested leverage (1 = spot-equivalent)
    vol_usd: float = 0.0             # 24h volume
    timeframe: str = "5m"            # primary TF for this signal
    setup_type: str = "neutral"       # human-readable setup label
    reason: str = ""                  # why this signal was generated
    features: dict = field(default_factory=dict)  # ML / context features
    timestamp: float = field(default_factory=time.time)
    # Strategy-specific exit parameters (override global defaults in position_manager)
    trail_activate_pct: float = 0.0    # 0 = use global default
    trail_distance_pct: float = 0.0    # 0 = use global default
    max_hold_minutes: float = 0.0      # 0 = use global default

    @property
    def risk_reward(self) -> float:
        if self.stop_loss_pct == 0:
            return 0.0
        return abs(self.tp1_pct / self.stop_loss_pct)

    def to_setup_dict(self) -> dict:
        """Convert to the setup dict format expected by position_manager.open_position."""
        return {
            "symbol": self.symbol,
            "strategy": self.strategy,
            "direction": self.direction,
            "setup_type": self.setup_type,
            "ta_score": self.score,
            "price": self.entry_price,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit": self.take_profit_1,
            "take_profit_2": self.take_profit_2,
            "confidence": self.confidence,
            "leverage": self.leverage,
            "vol_usd": self.vol_usd,
            "reason": self.reason,
            "features": self.features,
            "entry_zone": {
                "entry": self.entry_price,
                "stop_loss": self.stop_loss,
                "take_profit_1": self.take_profit_1,
                "take_profit_2": self.take_profit_2,
                "risk_per_unit": abs(self.entry_price - self.stop_loss) if self.stop_loss else 0.0,
                "rr_ratio": self.risk_reward,
            },
            "decision": {
                "action": "enter",
                "posterior": self.confidence,
                "threshold": 0.45,
                "r_multiple": self.risk_reward,
            },
            "strategy_exit_params": {
                "stop_loss_pct": self.stop_loss_pct,
                "trail_activate_pct": self.trail_activate_pct,
                "trail_distance_pct": self.trail_distance_pct,
                "max_hold_minutes": self.max_hold_minutes,
                "tp1_pct": self.tp1_pct,
                "tp2_pct": self.tp2_pct,
            },
        }


class BaseStrategy(ABC):
    """Abstract base for all trading strategies."""

    name: str = "base"
    max_signals_per_cycle: int = 5

    def __init__(self, exchange, config: dict | None = None):
        self.exchange = exchange
        self.config = config or {}
        self._last_scan_time = 0.0
        self._scan_interval = float(self.config.get("scan_interval_seconds", 15))
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, val: bool):
        self._enabled = val

    @abstractmethod
    async def scan(self, regime: str = "sideways") -> list[StrategySignal]:
        """Scan the market and return a list of entry signals.
        
        Called every cycle. Must be fast (<5s).
        Returns up to max_signals_per_cycle signals, ranked by score.
        """
        ...

    @abstractmethod
    def check_exit(self, position: dict, current_price: float, regime: str = "sideways") -> Optional[str]:
        """Check if an open position should exit.
        
        Args:
            position: dict with keys like entry_price, amount, highest_price, 
                      hold_time_seconds, pnl_pct, strategy, etc.
            current_price: current market price
            regime: current market regime
            
        Returns:
            None if hold, or exit reason string (e.g., "scalp_tp", "scalp_sl")
        """
        ...

    def should_scan(self) -> bool:
        """Rate-limit scanning."""
        now = time.time()
        if now - self._last_scan_time >= self._scan_interval:
            self._last_scan_time = now
            return True
        return False

    async def _fetch_candles(self, symbol: str, timeframe: str = "5m", limit: int = 100) -> list:
        """Helper to fetch OHLCV candles via exchange connector."""
        try:
            return await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        except Exception as e:
            logger.debug(f"[{self.name}] Failed to fetch {timeframe} candles for {symbol}: {e}")
            return []

    async def _fetch_ticker(self, symbol: str) -> dict:
        """Helper to fetch ticker."""
        try:
            return await self.exchange.fetch_ticker(symbol)
        except Exception as e:
            logger.debug(f"[{self.name}] Failed to fetch ticker for {symbol}: {e}")
            return {}

    @staticmethod
    def is_pump_exhausted(highs: list[float], closes: list[float], direction: str = "long") -> tuple[bool, float]:
        """Check if a pump has already peaked and is pulling back.

        For longs: if current price is >2.5% below the high of the last 12
        candles (~1h on 5m), the pump is dying — do NOT enter.
        For shorts: mirror logic (price bounced too far above recent low).

        Returns (exhausted: bool, pullback_pct: float).
        """
        if len(highs) < 12 or len(closes) < 1:
            return False, 0.0
        if direction == "long":
            recent_high = max(highs[-12:])
            if recent_high <= 0:
                return False, 0.0
            pullback_pct = (recent_high - closes[-1]) / recent_high * 100.0
            return pullback_pct >= 2.5, pullback_pct
        else:
            recent_low = min([h for h in highs[-12:]])  # use lows if available
            if recent_low <= 0:
                return False, 0.0
            bounce_pct = (closes[-1] - recent_low) / recent_low * 100.0
            return bounce_pct >= 2.5, bounce_pct

    @staticmethod
    def ema(closes: list[float], period: int) -> list[float]:
        """Compute EMA from a list of close prices."""
        if len(closes) < period:
            return closes[:]
        result = []
        mult = 2.0 / (period + 1)
        sma = sum(closes[:period]) / period
        result = [0.0] * (period - 1) + [sma]
        for i in range(period, len(closes)):
            val = (closes[i] - result[-1]) * mult + result[-1]
            result.append(val)
        return result

    @staticmethod
    def rsi(closes: list[float], period: int = 14) -> float:
        """Compute RSI from close prices. Returns last RSI value."""
        if len(closes) < period + 1:
            return 50.0
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
        """Compute ATR. Returns last ATR value."""
        if len(highs) < period + 1:
            return 0.0
        trs = []
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)
        if len(trs) < period:
            return sum(trs) / len(trs) if trs else 0.0
        atr_val = sum(trs[:period]) / period
        for i in range(period, len(trs)):
            atr_val = (atr_val * (period - 1) + trs[i]) / period
        return atr_val

    @staticmethod
    def vwap(highs: list[float], lows: list[float], closes: list[float], volumes: list[float]) -> float:
        """Compute VWAP from HLC and volume arrays. Returns last VWAP value."""
        if not volumes or len(volumes) != len(closes):
            return closes[-1] if closes else 0.0
        cum_vol = 0.0
        cum_tp_vol = 0.0
        for i in range(len(closes)):
            tp = (highs[i] + lows[i] + closes[i]) / 3.0
            cum_vol += volumes[i]
            cum_tp_vol += tp * volumes[i]
        return cum_tp_vol / cum_vol if cum_vol > 0 else closes[-1]

    @staticmethod
    def bollinger_bands(closes: list[float], period: int = 20, std_mult: float = 2.0) -> tuple[float, float, float]:
        """Returns (upper, middle, lower) Bollinger Bands."""
        if len(closes) < period:
            mid = closes[-1] if closes else 0.0
            return mid, mid, mid
        window = closes[-period:]
        mid = sum(window) / period
        variance = sum((x - mid) ** 2 for x in window) / period
        std = variance ** 0.5
        return mid + std_mult * std, mid, mid - std_mult * std

    @staticmethod
    def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float, float, float]:
        """Returns (macd_line, signal_line, histogram)."""
        if len(closes) < slow + signal:
            return 0.0, 0.0, 0.0
        
        def _ema_series(data, period):
            mult = 2.0 / (period + 1)
            ema = [sum(data[:period]) / period]
            for val in data[period:]:
                ema.append((val - ema[-1]) * mult + ema[-1])
            return ema

        ema_fast = _ema_series(closes, fast)
        ema_slow = _ema_series(closes, slow)
        offset = slow - fast
        macd_line = [ema_fast[i + offset] - ema_slow[i] for i in range(len(ema_slow))]
        if len(macd_line) < signal:
            return macd_line[-1] if macd_line else 0.0, 0.0, 0.0
        sig = _ema_series(macd_line, signal)
        hist = macd_line[-1] - sig[-1]
        return macd_line[-1], sig[-1], hist
