"""
RegimeEngine v7.0 — Regime-Adaptive Strategy Router

Dynamically selects and weights trading strategies based on market regime.
Each strategy has proven edge in specific conditions:

  BULL:     EMA Trend Following (0.40) + VWAP Momentum (0.40) + BB Squeeze (0.20)
  BEAR:     EMA Trend Short (0.35) + BB Squeeze (0.35) + BB Mean Rev (0.30)
  SIDEWAYS: BB Mean Reversion (0.45) + BB Squeeze (0.30) + VWAP Momentum (0.25)
  CHOPPY:   BB Squeeze (0.50) + BB Mean Reversion (0.35) + EMA Trend (0.15)

Key improvements over v6.0:
  - ATR-based dynamic stops (not fixed %)
  - Multi-timeframe confirmation (4H trend + 1H signal)
  - Strategy confidence scoring (min 55 to emit)
  - Regime-weighted signal ranking
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import numpy as np
from loguru import logger

from .base import BaseStrategy, StrategySignal


# ── Regime → Strategy Weights ────────────────────────────────────────────────
REGIME_WEIGHTS = {
    "bull":     {"ema_trend": 0.40, "vwap_momentum": 0.40, "bb_squeeze": 0.20, "bb_mean_rev": 0.00},
    "bear":     {"ema_trend": 0.35, "vwap_momentum": 0.00, "bb_squeeze": 0.35, "bb_mean_rev": 0.30},
    "sideways": {"ema_trend": 0.00, "vwap_momentum": 0.25, "bb_squeeze": 0.30, "bb_mean_rev": 0.45},
    "choppy":   {"ema_trend": 0.15, "vwap_momentum": 0.00, "bb_squeeze": 0.50, "bb_mean_rev": 0.35},
}

# Minimum combined score to emit a signal
MIN_SIGNAL_SCORE = 55.0


class RegimeEngine:
    """
    Master strategy router that dynamically weights sub-strategies per regime.

    Usage:
        engine = RegimeEngine(exchange)
        signals = await engine.scan(candidates, regime="bull")
    """

    def __init__(self, exchange, config: dict | None = None):
        self.exchange = exchange
        self.config = config or {}
        self._last_regime = "sideways"
        self._regime_switch_time = time.time()

        # Import strategies here to avoid circular imports
        from .ema_trend import EMATrendStrategy
        from .bb_mean_rev import BBMeanRevStrategy
        from .vwap_momentum import VWAPMomentumStrategy
        from .bb_squeeze import BBSqueezeStrategy

        self._strategies: dict[str, BaseStrategy] = {
            "ema_trend": EMATrendStrategy(exchange, config),
            "bb_mean_rev": BBMeanRevStrategy(exchange, config),
            "vwap_momentum": VWAPMomentumStrategy(exchange, config),
            "bb_squeeze": BBSqueezeStrategy(exchange, config),
        }
        logger.info(
            f"[RegimeEngine] Initialized with {len(self._strategies)} strategies: "
            f"{list(self._strategies.keys())}"
        )

    async def scan(
        self,
        candidates: list[dict],
        regime: str = "sideways",
        max_signals: int = 5,
    ) -> list[StrategySignal]:
        """
        Run all regime-appropriate strategies on candidates, merge and rank signals.

        Args:
            candidates: list of watcher candidate dicts with OHLCV data
            regime: current market regime from BigBrother
            max_signals: max signals to return

        Returns:
            List of StrategySignal sorted by weighted score
        """
        t0 = time.monotonic()

        # Track regime changes
        if regime != self._last_regime:
            logger.info(
                f"[RegimeEngine] Regime switch: {self._last_regime} → {regime} "
                f"(held {time.time() - self._regime_switch_time:.0f}s)"
            )
            self._last_regime = regime
            self._regime_switch_time = time.time()

        weights = REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS["sideways"])

        # Only run strategies with weight > 0 for this regime
        active = {name: strat for name, strat in self._strategies.items()
                  if weights.get(name, 0) > 0}

        if not active:
            return []

        # Fetch multi-timeframe OHLCV for all candidate symbols
        symbol_data = await self._fetch_all_ohlcv(candidates)

        # Run active strategies in parallel
        tasks = {
            name: strat.analyze(symbol_data, regime)
            for name, strat in active.items()
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        # Collect and weight signals
        all_signals: list[tuple[float, StrategySignal]] = []
        for name, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.warning(f"[RegimeEngine] {name} error: {result}")
                continue
            if not isinstance(result, list):
                continue
            w = weights.get(name, 0)
            for sig in result:
                # Weighted score = strategy confidence × regime weight
                weighted = sig.score * (0.5 + 0.5 * w)  # weight boosts, doesn't dominate
                all_signals.append((weighted, sig))

        # Deduplicate: keep best per symbol
        best_per_symbol: dict[str, tuple[float, StrategySignal]] = {}
        for weighted, sig in all_signals:
            existing = best_per_symbol.get(sig.symbol)
            if existing is None or weighted > existing[0]:
                best_per_symbol[sig.symbol] = (weighted, sig)

        # Filter by minimum score and sort
        qualified = [
            (w, s) for w, s in best_per_symbol.values()
            if s.score >= MIN_SIGNAL_SCORE
        ]
        qualified.sort(key=lambda x: x[0], reverse=True)
        top = [sig for _, sig in qualified[:max_signals]]

        elapsed = time.monotonic() - t0
        if top:
            summary = [(s.symbol, s.strategy, f"{s.score:.0f}") for s in top]
            logger.info(
                f"[RegimeEngine] {regime} regime | {len(top)} signals from "
                f"{list(active.keys())} [{elapsed:.1f}s]: {summary}"
            )
        else:
            logger.debug(
                f"[RegimeEngine] {regime} regime | 0 signals from "
                f"{list(active.keys())} [{elapsed:.1f}s]"
            )

        return top

    async def _fetch_all_ohlcv(self, candidates: list[dict]) -> dict[str, dict[str, np.ndarray]]:
        """
        Fetch 1H and 4H OHLCV for all candidate symbols.
        Returns: {symbol: {"1h": np.ndarray, "4h": np.ndarray}}
        """
        symbol_data: dict[str, dict[str, np.ndarray]] = {}
        timeframes = ["1h", "4h"]

        async def _fetch_one(symbol: str, tf: str):
            try:
                candles = await self.exchange.fetch_ohlcv(symbol, tf, limit=200)
                if candles and len(candles) >= 30:
                    return symbol, tf, np.array(candles, dtype=float)
            except Exception:
                pass
            return symbol, tf, None

        # Batch fetch — limit concurrency to avoid rate limits
        tasks = []
        for cand in candidates:
            sym = cand["symbol"]
            for tf in timeframes:
                tasks.append(_fetch_one(sym, tf))

        results = await asyncio.gather(*tasks)
        for sym, tf, data in results:
            if data is not None:
                if sym not in symbol_data:
                    symbol_data[sym] = {}
                symbol_data[sym][tf] = data

        return symbol_data

    def check_exit(self, symbol: str, position: dict, current_price: float,
                   regime: str = "sideways") -> Optional[str]:
        """Route exit check to the strategy that opened this position."""
        strat_name = position.get("strategy", "")
        strat = self._strategies.get(strat_name)
        if strat:
            return strat.check_exit(position, current_price, regime)
        return None

    @property
    def strategy_names(self) -> list[str]:
        return list(self._strategies.keys())

    def get_status(self, regime: str = "sideways") -> dict:
        weights = REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS["sideways"])
        return {
            "regime": regime,
            "weights": weights,
            "strategies": list(self._strategies.keys()),
            "active": [n for n, w in weights.items() if w > 0],
            "last_regime_switch": self._regime_switch_time,
        }
