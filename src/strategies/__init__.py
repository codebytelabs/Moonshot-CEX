"""
Strategy modules for Moonshot-CEX multi-strategy trading engine.

Strategies:
  - ScalpingSniper: High-frequency 1m/5m scalping (60-70% WR, fast ROI)
  - BreakoutORB: Opening Range Breakout momentum (55-65% WR, big moves)
  - MeanReversion: Oversold bounce / overextended fade (60-70% WR)
"""
from .base import BaseStrategy, StrategySignal
from .scalper import ScalpingSniper
from .breakout import BreakoutORB
from .mean_reversion import MeanReversionStrategy

__all__ = [
    "BaseStrategy",
    "StrategySignal",
    "ScalpingSniper",
    "BreakoutORB",
    "MeanReversionStrategy",
]
