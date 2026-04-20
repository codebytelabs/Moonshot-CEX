import os
import sys
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.strategies.bb_squeeze import BBSqueezeStrategy


def _build_tf(closes: np.ndarray, last_volume: float = 2.0) -> np.ndarray:
    data = np.zeros((len(closes), 6), dtype=float)
    data[:, 2] = closes + 0.01
    data[:, 3] = closes - 0.01
    data[:, 4] = closes
    data[:, 5] = 1.0
    data[-1, 5] = last_volume
    return data


def _make_strategy() -> BBSqueezeStrategy:
    strategy = BBSqueezeStrategy(exchange=MagicMock())
    strategy._detect_squeeze = lambda highs, lows, closes: (False, 4)
    strategy.ema = lambda closes, period: np.linspace(1.0, 1.1, len(closes)).tolist()
    strategy.rsi = lambda closes, period=14: 60.0
    strategy.atr = lambda highs, lows, closes, period=14: 0.02
    return strategy


def test_bb_squeeze_breakout_uses_125_trailing_activation_in_sideways():
    strategy = _make_strategy()
    tf_data = {
        "1h": _build_tf(np.linspace(1.0, 1.1, 60)),
        "4h": _build_tf(np.linspace(1.0, 1.2, 60)),
    }

    signal = strategy._analyze_one("DOT/USDT:USDT", tf_data, regime="sideways")

    assert signal is not None
    assert signal.setup_type == "bb_squeeze_breakout"
    assert signal.trail_activate_pct == 1.25



def test_bb_squeeze_breakout_keeps_earlier_trailing_in_bear():
    strategy = _make_strategy()
    tf_data = {
        "1h": _build_tf(np.linspace(1.0, 1.1, 60)),
        "4h": _build_tf(np.linspace(1.0, 1.2, 60)),
    }

    signal = strategy._analyze_one("DOT/USDT:USDT", tf_data, regime="bear")

    assert signal is not None
    assert signal.trail_activate_pct == 1.0
