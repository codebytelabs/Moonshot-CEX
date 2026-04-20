import os
import sys
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.strategies.ema_trend import EMATrendStrategy


def _make_candles(closes: list[float], volume_base: float = 1000.0) -> np.ndarray:
    rows = []
    for i, close in enumerate(closes):
        open_price = closes[i - 1] if i > 0 else close * 0.995
        high = max(open_price, close) * 1.01
        low = min(open_price, close) * 0.99
        volume = volume_base * (1.8 if i == len(closes) - 1 else 1.0)
        rows.append([i, open_price, high, low, close, volume])
    return np.array(rows, dtype=float)


def _make_strategy() -> EMATrendStrategy:
    strategy = EMATrendStrategy(exchange=MagicMock())
    strategy._compute_adx = lambda highs, lows, closes, period=14: 32.0
    strategy.rsi = lambda closes, period=14: 62.0
    strategy.atr = lambda highs, lows, closes, period=14: 2.0
    return strategy


def _make_bull_data() -> dict[str, np.ndarray]:
    closes_1h = [100 + i * 0.2 for i in range(190)]
    closes_1h += [131.0, 130.5, 130.0, 130.8, 131.6, 132.4, 133.2, 134.0, 135.0, 136.0]
    closes_4h = [100 + i * 0.8 for i in range(60)]
    return {"1h": _make_candles(closes_1h), "4h": _make_candles(closes_4h)}


def test_ema_trend_still_fires_in_bull_regime():
    strategy = _make_strategy()
    signal = strategy._analyze_one("BTC/USDT", _make_bull_data(), regime="bull")
    assert signal is not None
    assert signal.direction == "long"
    assert signal.setup_type == "ema_trend_follow"


def test_ema_trend_blocked_in_choppy_regime():
    strategy = _make_strategy()
    assert strategy._analyze_one("BTC/USDT", _make_bull_data(), regime="choppy") is None


def test_ema_trend_blocked_in_bear_regime():
    strategy = _make_strategy()
    assert strategy._analyze_one("BTC/USDT", _make_bull_data(), regime="bear") is None
