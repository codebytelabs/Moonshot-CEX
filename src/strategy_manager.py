"""
Strategy Manager — Orchestrates multiple trading strategies.

Runs all enabled strategies in parallel, deduplicates signals,
applies risk gating, and feeds signals to the execution pipeline.

Each strategy operates independently with its own:
  - Scanning logic and timeframes
  - Entry criteria and scoring
  - Exit rules per-position

The manager handles:
  - Strategy lifecycle (init, scan, exit checks)
  - Signal deduplication (same symbol from multiple strategies)
  - Position-strategy mapping (which strategy owns which position)
  - Aggregate risk limits across all strategies
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from loguru import logger

from .strategies.base import BaseStrategy, StrategySignal
from .strategies.scalper import ScalpingSniper
from .strategies.breakout import BreakoutORB
from .strategies.mean_reversion import MeanReversionStrategy


class StrategyManager:
    """Manages multiple concurrent trading strategies."""

    def __init__(self, exchange, config: dict | None = None):
        self.exchange = exchange
        self.config = config or {}
        self._strategies: dict[str, BaseStrategy] = {}
        self._position_strategy_map: dict[str, str] = {}  # symbol -> strategy_name
        self._signal_cooldowns: dict[str, float] = {}  # symbol -> last_signal_time
        self._cooldown_seconds = float(self.config.get("signal_cooldown_seconds", 60))
        self._max_total_positions = int(self.config.get("max_total_positions", 5))
        self._max_per_strategy = int(self.config.get("max_per_strategy", 3))

        self._init_strategies()

    def _init_strategies(self):
        """Initialize all strategy instances."""
        scalper_cfg = self.config.get("scalper", {})
        breakout_cfg = self.config.get("breakout", {})
        mean_rev_cfg = self.config.get("mean_reversion", {})

        self._strategies["scalper"] = ScalpingSniper(self.exchange, scalper_cfg)
        self._strategies["breakout"] = BreakoutORB(self.exchange, breakout_cfg)
        self._strategies["mean_reversion"] = MeanReversionStrategy(self.exchange, mean_rev_cfg)

        # ── v6.0 OVERHAUL: disable underperforming strategies ───────────
        # Trade data analysis: scalper 0% WR, mean_reversion 0% WR.
        # Only breakout strategy produces viable signals. Keep scalper/mean_rev
        # instantiated but disabled so they can be re-enabled without code changes.
        self._strategies["scalper"]._enabled = False
        self._strategies["mean_reversion"]._enabled = False

        enabled = [name for name, s in self._strategies.items() if s.enabled]
        logger.info(f"[StrategyManager] Initialized {len(enabled)} strategies: {enabled}")

    def get_strategy(self, name: str) -> Optional[BaseStrategy]:
        return self._strategies.get(name)

    def enable_strategy(self, name: str):
        if name in self._strategies:
            self._strategies[name].enabled = True
            logger.info(f"[StrategyManager] Enabled: {name}")

    def disable_strategy(self, name: str):
        if name in self._strategies:
            self._strategies[name].enabled = False
            logger.info(f"[StrategyManager] Disabled: {name}")

    @property
    def active_strategies(self) -> list[str]:
        return [n for n, s in self._strategies.items() if s.enabled]

    def register_position(self, symbol: str, strategy_name: str):
        """Track which strategy opened a position."""
        self._position_strategy_map[symbol] = strategy_name

    def unregister_position(self, symbol: str):
        """Remove position tracking when closed."""
        self._position_strategy_map.pop(symbol, None)

    def get_position_strategy(self, symbol: str) -> Optional[str]:
        return self._position_strategy_map.get(symbol)

    def positions_for_strategy(self, strategy_name: str) -> list[str]:
        return [s for s, n in self._position_strategy_map.items() if n == strategy_name]

    async def scan_all(self, regime: str = "sideways", open_positions: list[str] | None = None) -> list[StrategySignal]:
        """Run all enabled strategies in parallel and return deduplicated signals.
        
        Args:
            regime: current market regime
            open_positions: list of symbols currently held (to avoid duplicates)
        """
        open_set = set(open_positions or [])
        now = time.time()

        # Clean old cooldowns
        self._signal_cooldowns = {
            k: v for k, v in self._signal_cooldowns.items()
            if now - v < self._cooldown_seconds
        }

        # Check capacity
        current_count = len(self._position_strategy_map)
        if current_count >= self._max_total_positions:
            return []

        remaining_slots = self._max_total_positions - current_count

        # Run all enabled strategies in parallel
        tasks = {}
        for name, strategy in self._strategies.items():
            if not strategy.enabled:
                continue
            # Check per-strategy position limit
            strat_positions = len(self.positions_for_strategy(name))
            if strat_positions >= self._max_per_strategy:
                continue
            tasks[name] = strategy.scan(regime)

        if not tasks:
            return []

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        all_signals: list[StrategySignal] = []
        for name, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.warning(f"[StrategyManager] {name} scan error: {result}")
                continue
            if isinstance(result, list):
                all_signals.extend(result)

        # Deduplicate: keep highest score per symbol
        seen_symbols: dict[str, StrategySignal] = {}
        for sig in all_signals:
            # Skip if already holding this symbol
            if sig.symbol in open_set:
                continue
            # Skip if in cooldown
            if sig.symbol in self._signal_cooldowns:
                continue
            # Keep best score per symbol
            existing = seen_symbols.get(sig.symbol)
            if existing is None or sig.score > existing.score:
                seen_symbols[sig.symbol] = sig

        # Sort by score, limit to remaining slots
        deduped = sorted(seen_symbols.values(), key=lambda s: s.score, reverse=True)
        final = deduped[:remaining_slots]

        # Set cooldowns
        for sig in final:
            self._signal_cooldowns[sig.symbol] = now

        if final:
            summary = [(s.symbol, s.strategy, f"{s.score:.0f}") for s in final]
            logger.info(f"[StrategyManager] {len(final)} signals: {summary}")

        return final

    def check_exit(self, symbol: str, position: dict, current_price: float, regime: str = "sideways") -> Optional[str]:
        """Check exit for a position using its owning strategy's rules.
        
        Falls back to generic exit rules if strategy not found.
        """
        strategy_name = self._position_strategy_map.get(symbol)
        if not strategy_name:
            # Position opened by legacy system — use generic exit
            return self._generic_exit(position, current_price)

        strategy = self._strategies.get(strategy_name)
        if not strategy:
            return self._generic_exit(position, current_price)

        return strategy.check_exit(position, current_price, regime)

    @staticmethod
    def _generic_exit(position: dict, current_price: float) -> Optional[str]:
        """Generic exit rules for positions not owned by any strategy."""
        entry = float(position.get("entry_price", 0))
        if entry <= 0 or current_price <= 0:
            return None

        pnl_pct = (current_price - entry) / entry * 100
        highest = float(position.get("highest_price", current_price))
        peak_pnl = (highest - entry) / entry * 100
        hold_secs = float(position.get("hold_time_seconds", 0))
        hold_h = hold_secs / 3600.0

        # Stop loss: -3.5%
        if pnl_pct <= -3.5:
            return "generic_sl"
        # Trailing: +1% activate, 1% distance
        if peak_pnl >= 1.0 and (peak_pnl - pnl_pct) >= 1.0:
            return "generic_trail"
        # Time exit: 3h for losers
        if hold_h >= 3.0 and pnl_pct <= 0:
            return "generic_time"
        # Hard cap: 6h
        if hold_h >= 6.0:
            return "generic_time_max"
        return None

    def get_status(self) -> dict:
        """Return status dict for API/dashboard."""
        status = {
            "strategies": {},
            "total_positions": len(self._position_strategy_map),
            "max_positions": self._max_total_positions,
            "position_map": dict(self._position_strategy_map),
        }
        for name, strat in self._strategies.items():
            positions = self.positions_for_strategy(name)
            status["strategies"][name] = {
                "enabled": strat.enabled,
                "positions": len(positions),
                "symbols": positions,
                "max_per_strategy": self._max_per_strategy,
            }
        return status
