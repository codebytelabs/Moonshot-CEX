"""
Strategy modules for Moonshot-CEX multi-strategy trading engine.

v7.0 Regime-Adaptive Strategies:
  - EMATrendStrategy: Dual EMA trend following with ADX (bull/bear)
  - BBMeanRevStrategy: Bollinger Band mean reversion with RSI (sideways)
  - VWAPMomentumStrategy: VWAP + volume breakout momentum (transitions)
  - BBSqueezeStrategy: BB squeeze volatility breakout (choppy/consolidation)
  - RegimeEngine: Master router that weights strategies per regime

Legacy (v6.0):
  - ScalpingSniper: disabled
  - BreakoutORB: legacy breakout
  - MeanReversion: disabled
"""
from .base import BaseStrategy, StrategySignal
from .scalper import ScalpingSniper
from .breakout import BreakoutORB
from .mean_reversion import MeanReversionStrategy
from .ema_trend import EMATrendStrategy
from .bb_mean_rev import BBMeanRevStrategy
from .vwap_momentum import VWAPMomentumStrategy
from .bb_squeeze import BBSqueezeStrategy
from .regime_engine import RegimeEngine

__all__ = [
    "BaseStrategy",
    "StrategySignal",
    "ScalpingSniper",
    "BreakoutORB",
    "MeanReversionStrategy",
    "EMATrendStrategy",
    "BBMeanRevStrategy",
    "VWAPMomentumStrategy",
    "BBSqueezeStrategy",
    "RegimeEngine",
]
