"""
PositionManager — Full position lifecycle management.
Tracks open positions, manages tier exits, trailing stops, pyramiding, and time exits.
"""

import time
import uuid
from typing import Optional
from loguru import logger

from .execution_core import (
    ExecutionCore,
    SubMinimumAmountError,
    PositionAlreadyClosedError,
)
from .metrics import active_positions


class Position:
    """Represents a single open trade."""

    def __init__(
        self,
        symbol: str,
        entry_price: float,
        amount: float,
        amount_usd: float,
        stop_loss: float,
        take_profit_1: float,
        take_profit_2: float,
        setup_type: str = "unknown",
        decision: dict = None,
        entry_fill: dict = None,
        side: str = "long",
        leverage: int = 1,
    ):
        self.id = str(uuid.uuid4())[:8]
        self.symbol = symbol
        self.entry_price = entry_price
        self.amount = amount
        self.amount_usd = amount_usd
        self.stop_loss = stop_loss
        self.take_profit_1 = take_profit_1
        self.take_profit_2 = take_profit_2
        self.setup_type = setup_type
        self.decision = decision or {}
        self.entry_fill = entry_fill or {}
        self.side = side
        self.leverage = leverage

        self.status = "open"
        self.highest_price = entry_price
        self.lowest_price = entry_price
        self.trailing_stop: Optional[float] = None
        self.tier1_done = False
        self.tier2_done = False
        self.pyramid_count = 0

        # Dynamic TP trailing: store original distances so TPs can ratchet
        self._initial_tp1_dist = abs(take_profit_1 - entry_price)
        self._initial_tp2_dist = abs(take_profit_2 - entry_price)

        self.realized_pnl_usd = 0.0
        self.total_fees_usd = entry_fill.get("fee_usd", 0.0) if entry_fill else 0.0

        self.opened_at = int(time.time())
        self.closed_at: Optional[int] = None
        self.close_reason: Optional[str] = None

        # Futures: compute margin and liquidation price
        self.margin_usd = amount_usd / leverage if leverage > 1 else amount_usd
        self.liquidation_price = self._compute_liquidation_price()

        # Exchange-side stop-loss order ID (STOP_MARKET on Binance)
        # Protects position even when bot is down
        self.exchange_sl_order_id: Optional[str] = None

        # Strategy-specific exit params (override global defaults when present)
        # Keys: stop_loss_pct, trail_activate_pct, trail_distance_pct, max_hold_minutes
        self.strategy_exit_params: dict = {}

    def _compute_liquidation_price(self) -> float:
        """Estimate liquidation price for isolated margin futures position."""
        if self.leverage <= 1:
            return 0.0  # spot — no liquidation
        # Simplified: liq happens when loss = margin (minus maintenance margin ~0.4%)
        maint_margin_rate = 0.004
        margin_ratio = 1.0 / self.leverage
        if self.side == "long":
            return self.entry_price * (1 - margin_ratio + maint_margin_rate)
        else:  # short
            return self.entry_price * (1 + margin_ratio - maint_margin_rate)

    def current_pnl_pct(self, current_price: float) -> float:
        if self.entry_price <= 0:
            return 0.0
        if self.side == "short":
            return (self.entry_price - current_price) / self.entry_price * 100.0
        return (current_price - self.entry_price) / self.entry_price * 100.0

    def current_r_multiple(self, current_price: float) -> float:
        if self.side == "short":
            risk = self.stop_loss - self.entry_price
            if risk <= 0:
                return 0.0
            return (self.entry_price - current_price) / risk
        else:
            risk = self.entry_price - self.stop_loss
            if risk <= 0:
                return 0.0
            return (current_price - self.entry_price) / risk

    def unrealized_pnl_usd(self, current_price: float) -> float:
        if self.side == "short":
            return (self.entry_price - current_price) * self.amount
        return (current_price - self.entry_price) * self.amount

    def hold_time_hours(self) -> float:
        return (time.time() - self.opened_at) / 3600.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "status": self.status,
            "setup_type": self.setup_type,
            "entry_price": self.entry_price,
            "amount": self.amount,
            "amount_usd": self.amount_usd,
            "stop_loss": self.stop_loss,
            "take_profit_1": self.take_profit_1,
            "take_profit_2": self.take_profit_2,
            "highest_price": self.highest_price,
            "lowest_price": getattr(self, "lowest_price", self.entry_price),
            "trailing_stop": self.trailing_stop,
            "tier1_done": self.tier1_done,
            "tier2_done": self.tier2_done,
            "pyramid_count": self.pyramid_count,
            "realized_pnl_usd": round(self.realized_pnl_usd, 4),
            "total_fees_usd": round(self.total_fees_usd, 4),
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "close_reason": self.close_reason,
            "hold_time_hours": round(self.hold_time_hours(), 2),
            "posterior": self.decision.get("posterior", 0.0),
            "side": self.side,
            "leverage": getattr(self, "leverage", 1),
            "margin_usd": round(getattr(self, "margin_usd", self.amount_usd), 4),
            "liquidation_price": round(getattr(self, "liquidation_price", 0.0), 6),
            "exchange_sl_order_id": getattr(self, "exchange_sl_order_id", None),
            "strategy_exit_params": getattr(self, "strategy_exit_params", {}),
        }


class PositionManager:
    """Manages open positions: entry, exits (tiered + trailing + time), pyramiding."""

    def __init__(
        self,
        execution: ExecutionCore,
        trailing_activate_pct: float = 15.0,
        trailing_distance_pct: float = 8.0,
        tier1_exit_pct: float = 0.25,
        tier2_exit_pct: float = 0.25,
        time_exit_hours: float = 4.0,
        pyramid_enabled: bool = True,
        pyramid_max_adds: int = 2,
        pyramid_min_r: float = 1.5,
        max_sell_retries: int = 3,
        stop_loss_pct: float = -18.0,
        momentum_recheck_interval_minutes: int = 5,
        symbol_cooldown_minutes: float = 30.0,
    ):
        self.execution = execution
        self.trailing_activate_pct = trailing_activate_pct
        self.trailing_distance_pct = trailing_distance_pct
        self.tier1_exit_pct = tier1_exit_pct
        self.tier2_exit_pct = tier2_exit_pct
        self.time_exit_hours = time_exit_hours
        self.pyramid_enabled = pyramid_enabled
        self.pyramid_max_adds = pyramid_max_adds
        self.pyramid_min_r = pyramid_min_r
        self.max_sell_retries = max_sell_retries
        self.stop_loss_pct = stop_loss_pct
        self.momentum_recheck_interval_minutes = max(
            1, momentum_recheck_interval_minutes
        )
        self.symbol_cooldown_minutes: float = symbol_cooldown_minutes

        self._positions: dict[str, Position] = {}
        self._positions_being_exited: set[str] = set()
        self._closed_history: list[dict] = []
        # Cooldown tracking: symbol → epoch time of any exit
        self._symbol_cooldowns: dict[str, float] = {}
        # Session churn guard: symbol → list of entry epoch times (rolling 4h window)
        # Prevents the same token being re-entered 4+ times in 4 hours after repeatedly
        # failing (e.g. TRX opened 16×, ANIME 14× in one session with short cooldowns).
        self._symbol_entry_times: dict[str, list[float]] = {}
        # Track consecutive exit failures per position — ghost-close after 3
        self._exit_failure_count: dict[str, int] = {}

    # ── Exchange-side stop-loss management ─────────────────────────────────
    # Places STOP_MARKET orders on Binance so positions are protected even
    # when bot is crashed/restarting. Software SL still fires first normally.

    def _get_futures_exchange(self):
        """Get FuturesExchangeConnector from execution core (if in futures mode)."""
        return getattr(self.execution, "futures_exchange", None)

    async def _place_exchange_sl(self, pos: Position) -> None:
        """Place a STOP_MARKET order on the exchange for this position.

        Uses trailing_stop when available (tighter than original SL) so that
        trailing progress is preserved across restarts. Cancels any existing
        exchange SL first to prevent duplicate orders.
        """
        fc = self._get_futures_exchange()
        if fc is None or not hasattr(fc, "place_stop_loss_order"):
            return  # spot mode — no exchange SL
        if pos.stop_loss <= 0:
            return

        # Cancel existing exchange SL to prevent duplicates on restart/recovery
        if pos.exchange_sl_order_id:
            try:
                await fc.cancel_stop_loss_order(pos.symbol, pos.exchange_sl_order_id)
                logger.info(
                    f"[PM] Cancelled old exchange SL before re-placing: {pos.symbol} algoId={pos.exchange_sl_order_id}"
                )
            except Exception:
                pass  # old order may already be gone

        # Use trailing_stop if it's set and tighter than original SL
        # This preserves trailing progress across restarts
        effective_stop = pos.stop_loss
        if pos.trailing_stop is not None:
            if pos.side == "long" and pos.trailing_stop > pos.stop_loss:
                effective_stop = pos.trailing_stop
            elif pos.side == "short" and pos.trailing_stop < pos.stop_loss:
                effective_stop = pos.trailing_stop

        try:
            order = await fc.place_stop_loss_order(
                symbol=pos.symbol,
                side=pos.side,
                amount=pos.amount,
                stop_price=effective_stop,
            )
            if order:
                pos.exchange_sl_order_id = order.get("id")
                _label = "trailing" if effective_stop != pos.stop_loss else "entry SL"
                logger.info(
                    f"[PM] Exchange SL placed: {pos.symbol} {pos.side} "
                    f"stop={effective_stop:.6f} ({_label}) order_id={pos.exchange_sl_order_id}"
                )
        except Exception as e:
            logger.warning(f"[PM] Failed to place exchange SL for {pos.symbol}: {e}")

    async def _cancel_exchange_sl(self, pos: Position) -> None:
        """Cancel the exchange-side SL order (called when closing position)."""
        fc = self._get_futures_exchange()
        if fc is None or not pos.exchange_sl_order_id:
            return
        try:
            await fc.cancel_stop_loss_order(pos.symbol, pos.exchange_sl_order_id)
            pos.exchange_sl_order_id = None
        except Exception as e:
            logger.debug(f"[PM] Could not cancel exchange SL for {pos.symbol}: {e}")

    async def _update_exchange_sl(self, pos: Position, new_stop_price: float) -> None:
        """Update exchange SL to a new (tighter) price — cancel old, place new."""
        fc = self._get_futures_exchange()
        if fc is None or not hasattr(fc, "update_stop_loss_order"):
            return
        if new_stop_price <= 0:
            return
        try:
            old_id = pos.exchange_sl_order_id or ""
            order = await fc.update_stop_loss_order(
                symbol=pos.symbol,
                old_order_id=old_id,
                side=pos.side,
                amount=pos.amount,
                new_stop_price=new_stop_price,
            )
            if order:
                pos.exchange_sl_order_id = order.get("id")
        except Exception as e:
            logger.debug(f"[PM] Could not update exchange SL for {pos.symbol}: {e}")

    async def _reconcile_exit_from_fills(
        self, pos: Position, fallback_price: float
    ) -> tuple[float, float, float, bool]:
        """Reconcile actual exit PnL from exchange fill history.

        Returns (reconciled_pnl, reconciled_exit_price, close_fees, from_fills_bool).
        Falls back to (pos.unrealized_pnl_usd(fallback_price), fallback_price, 0.0, False)
        if fetch_my_trades unavailable or no closing fills found.

        v7.7: Centralized helper — force_ghost, OrphanSweep, and exchange_closed paths
        all use this to capture TRUE exit price from exchange-side algo SL/TP fills
        instead of the bot's current-tick price (which can be wildly wrong when the
        exchange has already closed the position at a different price).
        """
        reconciled_pnl = pos.unrealized_pnl_usd(fallback_price)
        reconciled_exit_price = fallback_price
        close_fees = 0.0
        from_fills = False

        fc = self._get_futures_exchange()
        if fc is None or not hasattr(fc, "fetch_my_trades"):
            return reconciled_pnl, reconciled_exit_price, close_fees, from_fills

        try:
            since_ms = int((pos.opened_at - 60) * 1000) if pos.opened_at else None
            fills = await fc.fetch_my_trades(pos.symbol, since=since_ms, limit=50)
            close_side = "sell" if pos.side == "long" else "buy"
            close_qty = 0.0
            close_cost = 0.0
            for t in fills or []:
                if t.get("side") != close_side:
                    continue
                q = float(t.get("amount") or 0)
                p_ = float(t.get("price") or 0)
                if q <= 0 or p_ <= 0:
                    continue
                close_qty += q
                close_cost += q * p_
                fee = t.get("fee") or {}
                close_fees += float(fee.get("cost", 0) or 0)
            if close_qty > 0:
                avg_exit = close_cost / close_qty
                if pos.side == "short":
                    tranche_pnl = (pos.entry_price - avg_exit) * close_qty
                else:
                    tranche_pnl = (avg_exit - pos.entry_price) * close_qty
                reconciled_pnl = pos.realized_pnl_usd + tranche_pnl
                reconciled_exit_price = avg_exit
                from_fills = True
        except Exception as e:
            logger.debug(f"[PM] Fill reconciliation failed for {pos.symbol}: {e}")

        return reconciled_pnl, reconciled_exit_price, close_fees, from_fills

    def is_symbol_on_cooldown(self, symbol: str) -> bool:
        """True if this symbol was recently stopped out and is still cooling down."""
        expires_at = self._symbol_cooldowns.get(symbol)
        if expires_at is None:
            return False
        if time.time() < expires_at:
            return True
        del self._symbol_cooldowns[symbol]
        return False

    def is_symbol_churning(
        self, symbol: str, window_hours: float = 4.0, max_entries: int = 3
    ) -> bool:
        """True if this symbol has been entered max_entries+ times in the last window_hours.
        Prevents repeatedly re-entering the same failing token (TRX/ANIME churn pattern).
        """
        now = time.time()
        cutoff = now - window_hours * 3600
        times = self._symbol_entry_times.get(symbol, [])
        recent = [t for t in times if t >= cutoff]
        self._symbol_entry_times[symbol] = recent
        return len(recent) >= max_entries

    def _record_entry(self, symbol: str) -> None:
        """Record an entry timestamp for churn tracking."""
        now = time.time()
        if symbol not in self._symbol_entry_times:
            self._symbol_entry_times[symbol] = []
        self._symbol_entry_times[symbol].append(now)

    def restore_position_from_dict(self, doc: dict) -> Optional["Position"]:
        """Reconstruct a Position from a MongoDB document (crash recovery).
        Returns None if the doc is missing required fields."""
        try:
            pos = Position.__new__(Position)
            pos.id = doc.get("id", str(uuid.uuid4())[:8])
            pos.symbol = doc["symbol"]
            pos.entry_price = float(doc["entry_price"])
            pos.amount = float(doc["amount"])
            pos.amount_usd = float(doc["amount_usd"])
            pos.stop_loss = float(doc["stop_loss"])
            pos.take_profit_1 = float(doc.get("take_profit_1", pos.entry_price * 1.04))
            pos.take_profit_2 = float(doc.get("take_profit_2", pos.entry_price * 1.10))
            pos.setup_type = doc.get("setup_type", "recovered")
            pos.decision = doc.get("decision") or {}
            pos.entry_fill = doc.get("entry_fill") or {}
            pos.status = "open"
            pos.highest_price = float(doc.get("highest_price", pos.entry_price))
            pos.lowest_price = float(doc.get("lowest_price", doc["entry_price"]))
            pos.trailing_stop = doc.get("trailing_stop")
            pos.tier1_done = bool(doc.get("tier1_done", False))
            pos.tier2_done = bool(doc.get("tier2_done", False))
            pos.pyramid_count = int(doc.get("pyramid_count", 0))
            pos.realized_pnl_usd = float(doc.get("realized_pnl_usd", 0.0))
            pos.total_fees_usd = float(doc.get("total_fees_usd", 0.0))
            pos.opened_at = int(doc.get("opened_at", time.time()))
            pos.closed_at = None
            pos.close_reason = None
            pos.side = doc.get("side", "long")
            pos.exchange_sl_order_id = doc.get("exchange_sl_order_id")
            pos.leverage = int(doc.get("leverage", 1))
            pos.margin_usd = float(doc.get("margin_usd", pos.amount_usd))
            pos.liquidation_price = float(doc.get("liquidation_price", 0.0))
            # Dynamic TP trailing: restore initial distances
            pos._initial_tp1_dist = abs(pos.take_profit_1 - pos.entry_price)
            pos._initial_tp2_dist = abs(pos.take_profit_2 - pos.entry_price)
            pos.strategy_exit_params = doc.get("strategy_exit_params", {})
            return pos
        except Exception as e:
            logger.warning(
                f"[PM] restore_position_from_dict failed: {e} | doc={doc.get('symbol', '?')}"
            )
            return None

    async def open_position(
        self,
        setup: dict,
        amount_usd: float,
        tier1_r: float = 2.0,
        tier2_r: float = 5.0,
    ) -> Optional[Position]:
        """Execute entry and register new position."""
        symbol = setup["symbol"]
        entry_zone = setup.get("entry_zone", {})
        price = float(setup.get("price", 0.0))
        direction = setup.get("direction", "long")
        leverage = int(setup.get("leverage", 1))

        # ── DUPLICATE POSITION GUARD ──────────────────────────────────────
        # Hard block: never open a second position on the same symbol.
        # Root cause: after restarts, crash recovery can miss positions
        # (transient exchange API), leaving the bot unaware of an existing
        # Binance position. Without this guard, the bot stacks 3+ entries
        # on one symbol (BTR opened 3× for $9k+ combined exposure).
        existing = self.get_position_for_symbol(symbol)
        if existing:
            logger.warning(
                f"[PM] BLOCKED duplicate open for {symbol} — already tracking "
                f"id={existing.id} entry={existing.entry_price:.6f}"
            )
            return None

        if direction == "long":
            stop_loss = float(
                entry_zone.get("stop_loss", price * 0.94)
            )  # fallback: 6% below entry
        else:
            stop_loss = float(
                entry_zone.get("stop_loss", price * 1.06)
            )  # short: 6% above entry

        if price <= 0:
            logger.warning(f"[PM] Skipping {symbol}: invalid price {price}")
            return None

        if direction == "long":
            risk_per_unit = price - stop_loss
            take_profit_1 = price + tier1_r * risk_per_unit
            take_profit_2 = price + tier2_r * risk_per_unit
        else:
            risk_per_unit = stop_loss - price
            take_profit_1 = price - tier1_r * risk_per_unit
            take_profit_2 = price - tier2_r * risk_per_unit

        entry_side = "buy" if direction == "long" else "sell"

        try:
            # Build kwargs — FuturesExecutionCore accepts leverage/direction
            entry_kwargs = dict(
                symbol=symbol,
                side=entry_side,
                amount_usd=amount_usd,
                price=price,
                setup_type=setup.get("setup_type", "unknown"),
            )
            if leverage > 1:
                entry_kwargs["leverage"] = leverage
                entry_kwargs["direction"] = direction
            fill = await self.execution.enter_position(**entry_kwargs)
        except Exception as e:
            logger.error(f"[PM] Entry failed for {symbol}: {e}")
            return None

        fill_price = fill["filled_price"]
        fill_amount = fill["filled_amount"]
        # Use actual leverage from fill (may differ from requested if
        # set_leverage fell back on -4028 for limited-bracket symbols)
        actual_leverage = int(fill.get("leverage", leverage))

        pos = Position(
            symbol=symbol,
            entry_price=fill_price,
            amount=fill_amount,
            amount_usd=fill["amount_usd"],
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            setup_type=setup.get("setup_type", "unknown"),
            decision=setup.get("decision", {}),
            entry_fill=fill,
            side=direction,
            leverage=actual_leverage,
        )
        # Propagate strategy-specific exit params so _tick_position uses them
        _strat_exit = setup.get("strategy_exit_params", {})
        if _strat_exit:
            pos.strategy_exit_params = _strat_exit
            logger.info(
                f"[PM] {symbol} strategy exit params: "
                f"sl={_strat_exit.get('stop_loss_pct')}% "
                f"trail={_strat_exit.get('trail_activate_pct')}/{_strat_exit.get('trail_distance_pct')}% "
                f"max_hold={_strat_exit.get('max_hold_minutes')}min"
            )
        self._positions[pos.id] = pos
        self._record_entry(symbol)
        active_positions.set(len(self._positions))
        logger.info(
            f"[PM] OPENED {symbol} {pos.side} {actual_leverage}x id={pos.id} "
            f"entry={fill_price:.6f} sl={stop_loss:.6f} "
            f"tp1={take_profit_1:.6f} amount=${fill['amount_usd']:.2f}"
            f"{' liq=' + f'{pos.liquidation_price:.6f}' if pos.liquidation_price > 0 else ''}"
        )

        # Place exchange-side stop-loss order (futures only)
        await self._place_exchange_sl(pos)

        return pos

    async def pyramid_add(
        self, pos: Position, current_price: float, add_usd: float
    ) -> bool:
        """Add to a winning position (pyramid into strength).

        Conditions:
        - pyramid_enabled must be True
        - pyramid_count < pyramid_max_adds
        - current R-multiple >= pyramid_min_r
        - position not being exited
        """
        if not self.pyramid_enabled:
            return False
        if pos.pyramid_count >= self.pyramid_max_adds:
            return False
        r_multiple = pos.current_r_multiple(current_price)
        if r_multiple < self.pyramid_min_r:
            return False
        if pos.id in self._positions_being_exited:
            return False

        try:
            fill = await self.execution.enter_position(
                symbol=pos.symbol,
                side="buy",
                amount_usd=add_usd,
                price=current_price,
                setup_type="pyramid_add",
            )
        except Exception as e:
            logger.error(f"[PM] Pyramid add failed for {pos.symbol}: {e}")
            return False

        filled_amount = float(fill.get("filled_amount", 0.0))
        if filled_amount <= 0:
            return False

        # Weight the new avg entry price
        total_amount = pos.amount + filled_amount
        pos.entry_price = (
            pos.entry_price * pos.amount + current_price * filled_amount
        ) / total_amount
        pos.amount = total_amount
        pos.amount_usd += float(fill.get("amount_usd", add_usd))
        pos.total_fees_usd += fill.get("fee_usd", 0.0)
        pos.pyramid_count += 1
        if current_price > pos.highest_price:
            pos.highest_price = current_price

        logger.info(
            f"[PM] PYRAMID ADD #{pos.pyramid_count} {pos.symbol}: "
            f"+{filled_amount:.6f} @ {current_price:.6f} "
            f"(R={r_multiple:.1f}x) new_avg={pos.entry_price:.6f}"
        )
        return True

    async def update_all(self, regime_params: Optional[dict] = None) -> list[dict]:
        """Tick all open positions — check exits and manage trailing stops."""
        exits = []
        for pos_id, pos in list(self._positions.items()):
            if pos.status != "open":
                continue
            try:
                result = await self._tick_position(pos, regime_params)
                if result:
                    exits.append(result)
            except Exception as _tick_err:
                logger.error(
                    f"[PM] Tick error for {pos.symbol} ({pos.id[:8]}): {_tick_err} — skipping this position this cycle"
                )
        return exits

    async def tighten_stops_for_regime(
        self, regime_params: dict, close_threshold_pct: float = -2.0
    ) -> list[Optional[dict]]:
        """Smart regime downgrade protection — tighten stops + close deep losers.

        Called when regime degrades (e.g. bull→choppy).  Unlike the old
        sweep_vulnerable_positions which nuked everything < 0.5%, this:
          1. Tightens stop-loss on ALL positions to the new (tighter) regime params
          2. Updates exchange-side SL orders to match
          3. Only force-closes positions that are deeply underwater (< close_threshold_pct)

        Returns list of exit results for force-closed positions.
        """
        exits = []
        sl_pct = abs(regime_params.get("stop_loss_pct", self.stop_loss_pct)) / 100.0

        for pos_id, pos in list(self._positions.items()):
            if pos.status != "open":
                continue
            if pos.id in self._positions_being_exited:
                continue
            if pos.setup_type in ("synced_holding", "exchange_holding"):
                continue

            try:
                current_price = await self.execution.get_current_price(pos.symbol)
                if current_price <= 0:
                    continue

                pnl_pct = pos.current_pnl_pct(current_price)

                # Force-close deeply underwater positions — they're just bleeding
                if pnl_pct < close_threshold_pct:
                    logger.warning(
                        f"[PM] REGIME PROTECT: closing {pos.symbol} "
                        f"(PnL {pnl_pct:+.2f}% < {close_threshold_pct}%) to stop bleeding"
                    )
                    result = await self._execute_exit(
                        pos, current_price, "regime_downgrade_close", pos.amount
                    )
                    if result:
                        exits.append(result)
                    continue

                # Tighten stop-loss to new regime params
                new_sl = (
                    pos.entry_price * (1 - sl_pct)
                    if pos.side == "long"
                    else pos.entry_price * (1 + sl_pct)
                )
                old_sl = pos.stop_loss

                if pos.side == "long" and new_sl > old_sl:
                    pos.stop_loss = new_sl
                    logger.info(
                        f"[PM] REGIME TIGHTEN: {pos.symbol} SL {old_sl:.6f} → {new_sl:.6f} "
                        f"(pnl={pnl_pct:+.2f}%)"
                    )
                    effective_stop = (
                        pos.trailing_stop
                        if (pos.trailing_stop and pos.trailing_stop > new_sl)
                        else new_sl
                    )
                    await self._update_exchange_sl(pos, effective_stop)
                elif pos.side == "short" and (old_sl <= 0 or new_sl < old_sl):
                    pos.stop_loss = new_sl
                    logger.info(
                        f"[PM] REGIME TIGHTEN: {pos.symbol} SL {old_sl:.6f} → {new_sl:.6f} "
                        f"(pnl={pnl_pct:+.2f}%)"
                    )
                    effective_stop = (
                        pos.trailing_stop
                        if (pos.trailing_stop and pos.trailing_stop < new_sl)
                        else new_sl
                    )
                    await self._update_exchange_sl(pos, effective_stop)

            except Exception as e:
                logger.error(f"[PM] Regime protect error for {pos.symbol}: {e}")

        return exits

    def _momentum_exit_reason(
        self,
        pos: Position,
        current_price: float,
        pnl_pct: float,
        regime_params: Optional[dict],
    ) -> Optional[str]:
        """Simplified momentum exit — DATA-DRIVEN OVERHAUL.

        Analysis of 37 real trades showed:
          - momentum_died / no_traction / stall exits: 0% win rate, -$884 total
          - trailing_stop: 100% win rate, only profitable exit
          - momentum_died_20m: 100% win rate (most patient = most profitable)

        New design:
          1. early_thesis_invalid: after 5 min, if position NEVER went positive
             and is losing >1%, the momentum thesis was never validated.
             Different from old exits: those killed positions that HAD peaked.
             This only kills positions where upside NEVER materialized.
          2. momentum_faded: had a significant peak but gave most of it back.
        Everything else: stop_loss → trailing_stop → time_exit.
        """
        hold_minutes = pos.hold_time_hours() * 60.0
        peak_pnl_pct = pos.current_pnl_pct(
            pos.highest_price if pos.side == "long" else pos.lowest_price
        )
        giveback_pct = peak_pnl_pct - pnl_pct

        # DISABLED (v5.0 Wave Rider): early_thesis_invalid had 0% win rate across
        # 31 trades (-$863 total). It killed 41% of all trades before trailing stop
        # could activate. The positions it killed would hit -3.5% SL anyway, but
        # disabling this allows some to RECOVER and reach trailing activation.
        # The stop-loss is the proper downside protector, not a 5-minute impatience exit.
        # if hold_minutes >= 5.0 and pnl_pct < -1.0 and peak_pnl_pct < 0.3:
        #     return "early_thesis_invalid"

        # Momentum faded: had a significant peak (+3%+) but gave back 70%+ of gains.
        # This is the ONE justified momentum exit — don't let a +5% winner turn into -2% loser.
        if (
            hold_minutes >= 30
            and peak_pnl_pct >= 3.0
            and giveback_pct >= max(peak_pnl_pct * 0.6, 2.0)
            and pnl_pct < 0.5
        ):
            return "momentum_faded"

        return None

    async def _tick_position(
        self, pos: Position, regime_params: Optional[dict]
    ) -> Optional[dict]:
        symbol = pos.symbol

        # Skip phantom zero-amount positions — they can't be sold
        if pos.amount_usd < 0.10 or pos.amount < 1e-8:
            return None

        try:
            current_price = await self.execution.get_current_price(symbol)
        except Exception as e:
            logger.debug(f"[PM] Price fetch error for {symbol}: {e}")
            return None

        if current_price <= 0:
            return None

        if current_price > pos.highest_price:
            pos.highest_price = current_price
        if current_price < pos.lowest_price:
            pos.lowest_price = current_price

        # ── Dynamic TP trailing — ratchet TPs as price makes new highs ────────
        # Static TPs (set at entry) miss profit on strong runners: a token that
        # runs +8% still had TP1 at +2.5%, taking profits way too early on the
        # pullback. Dynamic TPs trail behind highest_price so partial exits
        # capture more of the actual move.
        _tp1_dist = getattr(
            pos, "_initial_tp1_dist", abs(pos.take_profit_1 - pos.entry_price)
        )
        _tp2_dist = getattr(
            pos, "_initial_tp2_dist", abs(pos.take_profit_2 - pos.entry_price)
        )

        if pos.side == "long" and pos.highest_price > pos.entry_price:
            _excess = pos.highest_price - pos.entry_price
            # TP1: once price has covered 60% of original TP1 distance, start trailing
            # Trails at highest_price minus 50% of original TP1 distance (buffer zone)
            if _excess > _tp1_dist * 0.6 and not pos.tier1_done:
                new_tp1 = pos.highest_price - _tp1_dist * 0.5
                if new_tp1 > pos.take_profit_1:
                    logger.debug(
                        f"[PM] {symbol} TP1 ratchet: {pos.take_profit_1:.6f} → {new_tp1:.6f}"
                    )
                    pos.take_profit_1 = new_tp1
            # TP2: once price has covered 60% of original TP2 distance, start trailing
            if _excess > _tp2_dist * 0.6 and not pos.tier2_done:
                new_tp2 = pos.highest_price - _tp2_dist * 0.5
                if new_tp2 > pos.take_profit_2:
                    logger.debug(
                        f"[PM] {symbol} TP2 ratchet: {pos.take_profit_2:.6f} → {new_tp2:.6f}"
                    )
                    pos.take_profit_2 = new_tp2

        elif pos.side == "short" and pos.lowest_price < pos.entry_price:
            _excess = pos.entry_price - pos.lowest_price
            if _excess > _tp1_dist * 0.6 and not pos.tier1_done:
                new_tp1 = pos.lowest_price + _tp1_dist * 0.5
                if new_tp1 < pos.take_profit_1:
                    logger.debug(
                        f"[PM] {symbol} TP1 ratchet (short): {pos.take_profit_1:.6f} → {new_tp1:.6f}"
                    )
                    pos.take_profit_1 = new_tp1
            if _excess > _tp2_dist * 0.6 and not pos.tier2_done:
                new_tp2 = pos.lowest_price + _tp2_dist * 0.5
                if new_tp2 < pos.take_profit_2:
                    logger.debug(
                        f"[PM] {symbol} TP2 ratchet (short): {pos.take_profit_2:.6f} → {new_tp2:.6f}"
                    )
                    pos.take_profit_2 = new_tp2

        sl_pct = (
            regime_params.get("stop_loss_pct", self.stop_loss_pct)
            if regime_params
            else self.stop_loss_pct
        )
        trail_activate = (
            regime_params.get("trailing_activate_pct", self.trailing_activate_pct)
            if regime_params
            else self.trailing_activate_pct
        )
        trail_dist = (
            regime_params.get("trailing_distance_pct", self.trailing_distance_pct)
            if regime_params
            else self.trailing_distance_pct
        )
        effective_time_exit_hours = (
            regime_params.get("time_exit_hours", self.time_exit_hours)
            if regime_params
            else self.time_exit_hours
        )
        trail_price_dist = 0.0

        _sep = getattr(pos, "strategy_exit_params", {})
        if _sep:
            _s_sl = float(_sep.get("stop_loss_pct", 0))
            if _s_sl < 0:
                sl_pct = _s_sl
            _s_trail_act = float(_sep.get("trail_activate_pct", 0))
            if _s_trail_act > 0:
                trail_activate = _s_trail_act
            _s_trail_dist = float(_sep.get("trail_distance_pct", 0))
            if _s_trail_dist > 0:
                trail_dist = _s_trail_dist
            _s_trail_p_dist = float(_sep.get("trail_distance_price", 0))
            if _s_trail_p_dist > 0:
                trail_price_dist = _s_trail_p_dist
            _s_hold_min = float(_sep.get("max_hold_minutes", 0))
            if _s_hold_min > 0:
                effective_time_exit_hours = _s_hold_min / 60.0

        pnl_pct = pos.current_pnl_pct(current_price)
        r_multiple = pos.current_r_multiple(current_price)

        # ── Early Breakeven Ratchet (+0.5% MFE) ─────────────────────────────
        # v8.0: 23 losers (24% of all losses, -$944 total) went >1% positive
        # before reversing to SL. Median loser MFE was only 0.41%, but 23/96
        # broke +1% — they caught real momentum then reversed.
        # Moving SL to just inside BE at +0.5% MFE (not +3% = +1R) cuts the
        # "whipped" bleed where trades go positive then decay.
        # v8.0a fix: SL is placed at 0.998×entry (long) / 1.002×entry (short)
        # — just below BE so it doesn't sit on the entry line, with a
        # current_price buffer to avoid "Order would immediately trigger".
        if pos.side == "long" and pos.highest_price > pos.entry_price:
            _mfe_pct = 100.0 * (pos.highest_price - pos.entry_price) / pos.entry_price
            if _mfe_pct >= 0.5:
                _be_stop = pos.entry_price * 0.998
                _safe_gap = 1.002  # new SL must be >0.2% below current price
                if _be_stop > pos.stop_loss and current_price > _be_stop * _safe_gap:
                    logger.info(
                        f"[PM] Early BE ratchet {pos.symbol} (+{_mfe_pct:.2f}% MFE)"
                    )
                    pos.stop_loss = _be_stop
                    await self._update_exchange_sl(pos, pos.stop_loss)
        elif pos.side == "short" and pos.lowest_price < pos.entry_price:
            _mfe_pct = 100.0 * (pos.entry_price - pos.lowest_price) / pos.entry_price
            if _mfe_pct >= 0.5:
                _be_stop = pos.entry_price * 1.002
                _safe_gap = 0.998  # new SL must be >0.2% above current price
                if _be_stop < pos.stop_loss and pos.stop_loss > 0 and current_price < _be_stop * _safe_gap:
                    logger.info(
                        f"[PM] Early BE ratchet {pos.symbol} (+{_mfe_pct:.2f}% MFE)"
                    )
                    pos.stop_loss = _be_stop
                    await self._update_exchange_sl(pos, pos.stop_loss)

        # ── Breakeven Ratchet ────────────────────────────────────────────────
        # v7.7: Tightened from +1.5R to +1.0R. At SL=-3%, +1.0R = +3% profit.
        # Moving SL to breakeven at this level prevents profitable trades from
        # decaying to full -3% losers on normal pullbacks. Historical data showed
        # 67 of 208 losers had peaked above +1R before reversing.
        if r_multiple >= 1.0:
            if pos.side == "long":
                be_stop = pos.entry_price * 1.002
                if be_stop > pos.stop_loss:
                    logger.info(
                        f"[PM] Ratcheting SL to Breakeven for {pos.symbol} (R={r_multiple:.2f})"
                    )
                    pos.stop_loss = be_stop
                    await self._update_exchange_sl(pos, pos.stop_loss)
            elif pos.side == "short":
                be_stop = pos.entry_price * 0.998
                if be_stop < pos.stop_loss and pos.stop_loss > 0:
                    logger.info(
                        f"[PM] Ratcheting SL to Breakeven for {pos.symbol} (R={r_multiple:.2f})"
                    )
                    pos.stop_loss = be_stop
                    await self._update_exchange_sl(pos, pos.stop_loss)

        # Update dynamic stop loss — always ensure SL reflects configured percentage minimum
        abs_sl_pct = abs(sl_pct) / 100.0
        dynamic_sl = (
            pos.entry_price * (1 - abs_sl_pct)
            if pos.side == "long"
            else pos.entry_price * (1 + abs_sl_pct)
        )

        # For synced/exchange holdings with no stop loss, apply config-based SL
        # For bot positions, keep the tighter of: TA-based SL vs config-based SL
        if pos.stop_loss <= 0:
            pos.stop_loss = dynamic_sl
        elif pos.setup_type in ("synced_holding", "exchange_holding"):
            if pos.side == "long":
                pos.stop_loss = max(pos.stop_loss, dynamic_sl)
            else:
                pos.stop_loss = (
                    min(pos.stop_loss, dynamic_sl) if pos.stop_loss > 0 else dynamic_sl
                )

        # Trailing stop management
        if pnl_pct >= trail_activate:
            _old_trail = pos.trailing_stop
            if pos.side == "short":
                # Short: trail ABOVE lowest price
                if trail_price_dist > 0:
                    trail_price = pos.lowest_price + trail_price_dist
                else:
                    trail_price = pos.lowest_price * (1 + trail_dist / 100.0)
                if pos.trailing_stop is None or trail_price < pos.trailing_stop:
                    pos.trailing_stop = trail_price
            else:
                # Long: trail BELOW highest price
                if trail_price_dist > 0:
                    trail_price = pos.highest_price - trail_price_dist
                else:
                    trail_price = pos.highest_price * (1 - trail_dist / 100.0)
                if pos.trailing_stop is None or trail_price > pos.trailing_stop:
                    pos.trailing_stop = trail_price
            # Update exchange-side SL to follow the trailing stop
            if pos.trailing_stop != _old_trail and pos.trailing_stop is not None:
                await self._update_exchange_sl(pos, pos.trailing_stop)

        # ── Exit checks ──────────────────────────────────────────────────

        if pos.id in self._positions_being_exited:
            return None

        is_synced = pos.setup_type in ("synced_holding", "exchange_holding")

        # Hard stop loss — always applies
        if (
            (pos.side == "long" and current_price <= pos.stop_loss)
            or (pos.side == "short" and current_price >= pos.stop_loss)
            or pnl_pct <= sl_pct
        ):
            return await self._execute_exit(pos, current_price, "stop_loss", pos.amount)

        # Trailing stop — always applies
        if pos.trailing_stop and (
            (pos.side == "long" and current_price <= pos.trailing_stop)
            or (pos.side == "short" and current_price >= pos.trailing_stop)
        ):
            return await self._execute_exit(
                pos, current_price, "trailing_stop", pos.amount
            )

        hold_h = pos.hold_time_hours()

        # ── Bot-only: momentum_faded exit (the ONE justified momentum exit) ───
        # Data: all early momentum kills (died/stall/traction) had 0% win rate
        # and destroyed -$884 across 37 trades. Only momentum_faded (giving back
        # huge peaks) and trailing_stop (100% wr) were profitable.
        # The stop_loss (-3.5%) protects downside. Trailing (+1% activate) rides winners.
        # Time exit (2h) cleans up dead trades. No other momentum exits needed.
        if not is_synced:
            momentum_reason = self._momentum_exit_reason(
                pos, current_price, pnl_pct, regime_params
            )
            if momentum_reason:
                return await self._execute_exit(
                    pos, current_price, momentum_reason, pos.amount
                )

        # v8.0: 3h time_exit REMOVED (was: exit losing trade at 3h hold).
        # Live data: closed 63 positions for -$920 net, avg -$15/trade, killing
        # many positions before trailing stop could activate. The SL handles
        # real losers; the 6h safety cap below handles zombies. Trailing rides winners.
        # Safety cap: even profitable positions get a hard ceiling at 2× time limit
        # to prevent zombie positions that never trigger trailing.
        # Live data: time_exit_max closed 8 trades for +$178 (+$22 avg) — kept.
        if hold_h >= effective_time_exit_hours * 2:
            return await self._execute_exit(
                pos, current_price, "time_exit_max", pos.amount
            )

        # Tier 1 — partial exit when price hits dynamic TP1 (or R ≥ 1.0 as fallback)
        # v7.7: Fallback lowered 2.0 → 1.0 to match new TIER1_R_MULTIPLE=1.0
        # With dynamic TP trailing, TP1 ratchets up as price makes new highs,
        # so the partial exit fires at a higher price on strong runners.
        _tp1_hit = (pos.side == "long" and current_price >= pos.take_profit_1) or (
            pos.side == "short" and current_price <= pos.take_profit_1
        )
        if not pos.tier1_done and (_tp1_hit or r_multiple >= 1.0):
            tier1_amount = pos.amount * self.tier1_exit_pct
            result = await self._execute_partial_exit(
                pos, current_price, "tier1", tier1_amount
            )
            pos.tier1_done = True
            # Tighten trailing stop after T1
            if pos.trailing_stop:
                if pos.side == "short":
                    tighter = pos.lowest_price * (1 + (trail_dist * 0.75) / 100.0)
                    pos.trailing_stop = min(pos.trailing_stop, tighter)
                else:
                    tighter = pos.highest_price * (1 - (trail_dist * 0.75) / 100.0)
                    pos.trailing_stop = max(pos.trailing_stop, tighter)
                # Update exchange SL to match tightened trail
                await self._update_exchange_sl(pos, pos.trailing_stop)
            if result:
                return result

        # Tier 2 — partial exit when price hits dynamic TP2 (or R ≥ 5 as fallback)
        _tp2_hit = (pos.side == "long" and current_price >= pos.take_profit_2) or (
            pos.side == "short" and current_price <= pos.take_profit_2
        )
        # v7.7: Fallback lowered 5.0 → 2.0 to match new TIER2_R_MULTIPLE=2.0
        if pos.tier1_done and not pos.tier2_done and (_tp2_hit or r_multiple >= 2.0):
            tier2_amount = pos.amount * self.tier2_exit_pct
            result = await self._execute_partial_exit(
                pos, current_price, "tier2", tier2_amount
            )
            pos.tier2_done = True
            if result:
                return result

        # Pyramid add — add to a winner when R ≥ pyramid_min_r
        if (
            self.pyramid_enabled
            and r_multiple >= self.pyramid_min_r
            and pos.pyramid_count < self.pyramid_max_adds
        ):
            # Add 50% of original position size
            add_usd = pos.amount_usd * 0.5
            if add_usd >= 5.0:  # minimum sensible add
                await self.pyramid_add(pos, current_price, add_usd)

        return None

    async def _execute_exit(
        self, pos: Position, price: float, reason: str, amount: float
    ) -> Optional[dict]:
        """Execute a full position exit."""
        if pos.id in self._positions_being_exited:
            return None
        self._positions_being_exited.add(pos.id)
        try:
            # v7.7: Pre-flight check — if exchange has no position, skip market exit
            # entirely and go straight to fill reconciliation. Avoids the 5-retry
            # -2022 cascade when exchange-side algo SL has already closed the position.
            _exchange_has_position = True
            try:
                fc = self._get_futures_exchange()
                if fc is not None and hasattr(fc, "fetch_positions"):
                    ex_positions = await fc.fetch_positions([pos.symbol])
                    _exchange_has_position = any(
                        float(p.get("contracts", 0) or 0) > 0
                        for p in (ex_positions or [])
                        if p.get("symbol") == pos.symbol
                    )
            except Exception as _pc_err:
                logger.debug(f"[PM] Pre-exit position check failed {pos.symbol}: {_pc_err}")

            if not _exchange_has_position:
                logger.warning(
                    f"[PM] {pos.symbol} ({reason}): exchange has no position — "
                    f"skipping market exit, reconciling PnL from fills"
                )
                raise PositionAlreadyClosedError(pos.symbol, reason)

            # Cancel exchange-side SL order BEFORE exiting so Binance ReduceOnly orders aren't rejected (-2022)
            await self._cancel_exchange_sl(pos)

            fill = await self.execution.exit_position(
                pos.symbol, amount, price, reason, direction=pos.side
            )
            filled_amount = float(fill.get("filled_amount") or 0.0)  # type: ignore[arg-type]
            if filled_amount < amount * 0.999:
                if pos.side == "short":
                    partial_pnl = (
                        pos.entry_price - fill["filled_price"]
                    ) * filled_amount
                else:
                    partial_pnl = (
                        fill["filled_price"] - pos.entry_price
                    ) * filled_amount
                pos.realized_pnl_usd += partial_pnl
                pos.total_fees_usd += fill.get("fee_usd", 0.0)
                pos.amount = max(0.0, pos.amount - filled_amount)
                pos.amount_usd = pos.amount * pos.entry_price
                logger.warning(
                    f"[PM] EXIT PARTIAL {pos.symbol} ({reason}): "
                    f"filled={filled_amount:.6f} remaining={pos.amount:.6f}"
                )
                # Set cooldown on ALL partial fills — prevents opening a new position
                # while the old one is still in the partial-exit loop.
                # Old code: only stop_loss set cooldown → momentum_died/time_exit
                # partial fills had NO cooldown → new position opened same cycle →
                # remaining GREW (TRX: 49→76 tokens over 8 cycles).
                r = reason.lower()
                if any(
                    x in r
                    for x in (
                        "stop",
                        "momentum",
                        "time_exit",
                        "regime",
                        "hard_loss",
                        "no_traction",
                        "emergency",
                        "faded",
                        "stall",
                        "thesis",
                    )
                ):
                    cooldown_m = self.symbol_cooldown_minutes * (
                        1.5 if "stop" in r else 1.0
                    )
                    cooldown_until = time.time() + cooldown_m * 60
                    self._symbol_cooldowns[pos.symbol] = cooldown_until
                    logger.info(
                        f"[PM] Cooldown {pos.symbol} for {cooldown_m:.0f}m "
                        f"after partial {reason} (remaining={pos.amount:.6f})"
                    )
                return None
            # BUG FIX: Compute PnL on this final tranche using price×amount, not fill.amount_usd vs
            # pos.amount_usd — the latter is already reduced by prior tier exits, causing incorrect PnL.
            if pos.side == "short":
                final_tranche_pnl = (
                    pos.entry_price - fill["filled_price"]
                ) * filled_amount
            else:
                final_tranche_pnl = (
                    fill["filled_price"] - pos.entry_price
                ) * filled_amount
            pos.realized_pnl_usd += final_tranche_pnl
            pos.total_fees_usd += fill.get("fee_usd", 0.0)
            pos.status = "closed"
            pos.closed_at = int(time.time())
            pos.close_reason = reason

            pnl_usd = pos.realized_pnl_usd  # cumulative: tier1 + tier2 + final tranche
            if pos.side == "short":
                pnl_pct = (
                    (pos.entry_price - fill["filled_price"]) / pos.entry_price * 100.0
                )
            else:
                pnl_pct = (
                    (fill["filled_price"] - pos.entry_price) / pos.entry_price * 100.0
                )

            logger.info(
                f"[PM] CLOSED {pos.symbol} ({reason}): "
                f"pnl=${pnl_usd:.2f} ({pnl_pct:+.1f}%) "
                f"hold={pos.hold_time_hours():.1f}h"
            )

            closed = pos.to_dict()
            closed["exit_price"] = fill["filled_price"]
            closed["pnl_pct"] = round(pnl_pct, 2)
            closed["pnl_usd"] = round(
                pos.realized_pnl_usd, 4
            )  # required by server.py DB update check
            self._closed_history.append(closed)
            if len(self._closed_history) > 200:
                self._closed_history = self._closed_history[-200:]

            # ── Tiered cooldown by exit reason ────────────────────────────────
            # Danger exits (stop, regime sweep) → 45 min: coin is in trouble.
            # Momentum/time failures → 20-30 min: setup failed, give it a reset.
            # TP / trailing → 5-10 min: profitable exit, fresh signal may re-enter.
            # momentum_faded is the only momentum exit now (full close, not scale-down).
            r = reason.lower()
            if "btc_crash_sweep" in r:
                cooldown_m = (
                    self.symbol_cooldown_minutes * 3.0
                )  # 90 min: BTC crash — don't re-enter anything
            elif any(x in r for x in ("stop_loss", "regime_shift", "emergency")):
                cooldown_m = self.symbol_cooldown_minutes * 1.5  # 45 min
            elif any(x in r for x in ("no_traction", "time_exit")):
                cooldown_m = self.symbol_cooldown_minutes  # 30 min
            elif any(x in r for x in ("faded", "died", "stall", "thesis")):
                cooldown_m = self.symbol_cooldown_minutes * 0.67  # 20 min
            elif "trailing" in r:
                cooldown_m = max(8.0, self.symbol_cooldown_minutes * 0.33)  # 10 min
            elif any(x in r for x in ("tp", "take_profit", "tier1", "tier2")):
                cooldown_m = max(5.0, self.symbol_cooldown_minutes * 0.2)  # 6 min
            else:
                cooldown_m = self.symbol_cooldown_minutes  # 30 min default
            cooldown_until = time.time() + cooldown_m * 60
            self._symbol_cooldowns[pos.symbol] = cooldown_until
            logger.info(
                f"[PM] Cooldown {pos.symbol} for {cooldown_m:.0f}m after {reason}"
            )

            del self._positions[pos.id]
            active_positions.set(len(self._positions))
            return closed

        except SubMinimumAmountError as dust_err:
            # ── Ghost-close ────────────────────────────────────────────────
            # Amount is below exchange minimum — coins were already sold (prior
            # tier exits) or are unredeemable dust. Mark position closed without
            # placing any order, preserve already-realized PnL.
            logger.warning(
                f"[PM] GHOST-CLOSE {pos.symbol} ({reason}): "
                f"amount {dust_err.amount:.8f} below minimum {dust_err.min_amount:.8f}. "
                f"Closing as dust. Realized PnL so far: ${pos.realized_pnl_usd:.2f}"
            )
            await self._cancel_exchange_sl(pos)
            pos.status = "closed"
            pos.closed_at = int(time.time())
            pos.close_reason = f"{reason}_dust"
            # Trigger cooldown so we don't immediately re-enter the same pair
            cooldown_until = time.time() + self.symbol_cooldown_minutes * 60
            self._symbol_cooldowns[pos.symbol] = cooldown_until
            closed = pos.to_dict()
            closed["exit_price"] = dust_err.price
            closed["pnl_pct"] = round(
                (dust_err.price - pos.entry_price) / pos.entry_price * 100.0, 2
            )
            closed["pnl_usd"] = round(
                pos.realized_pnl_usd, 4
            )  # required by server.py DB update check
            self._closed_history.append(closed)
            if len(self._closed_history) > 200:
                self._closed_history = self._closed_history[-200:]
            del self._positions[pos.id]
            active_positions.set(len(self._positions))
            return closed

        except PositionAlreadyClosedError as pac_err:
            # ── Exchange closed the position (e.g. algo SL fired), bot unaware ──
            # Binance returned -2022 ReduceOnly. Retrying is futile. Ghost-close
            # immediately AND reconcile real PnL from exchange fill history so
            # stats reflect the actual win/loss instead of $0.
            logger.warning(
                f"[PM] EXCHANGE-CLOSED {pos.symbol} ({reason}): "
                f"position already flat on exchange. Reconciling PnL from fills."
            )
            _fallback_exit_price = price if price > 0 else pos.entry_price
            (
                reconciled_pnl,
                reconciled_exit_price,
                close_fees,
                _reconciled_from_fills,
            ) = await self._reconcile_exit_from_fills(pos, _fallback_exit_price)
            if _reconciled_from_fills:
                pos.total_fees_usd += close_fees
                logger.info(
                    f"[PM] Reconciled {pos.symbol}: exit≈${reconciled_exit_price:.6f} "
                    f"PnL=${reconciled_pnl:+.2f} (fees=${close_fees:.2f})"
                )
            else:
                logger.info(
                    f"[PM] {pos.symbol} PnL estimated from current price "
                    f"${_fallback_exit_price:.6f} (no matching fills): PnL=${reconciled_pnl:+.2f}"
                )

            await self._cancel_exchange_sl(pos)
            pos.realized_pnl_usd = reconciled_pnl
            pos.status = "closed"
            pos.closed_at = int(time.time())
            pos.close_reason = f"{reason}_exchange_closed"
            cooldown_until = time.time() + self.symbol_cooldown_minutes * 60
            self._symbol_cooldowns[pos.symbol] = cooldown_until
            closed = pos.to_dict()
            closed["exit_price"] = reconciled_exit_price
            closed["pnl_pct"] = round(
                ((reconciled_exit_price - pos.entry_price) / pos.entry_price * 100.0)
                * (-1 if pos.side == "short" else 1),
                2,
            )
            closed["pnl_usd"] = round(reconciled_pnl, 4)
            self._closed_history.append(closed)
            if len(self._closed_history) > 200:
                self._closed_history = self._closed_history[-200:]
            del self._positions[pos.id]
            self._exit_failure_count.pop(pos.id, None)
            active_positions.set(len(self._positions))
            return closed

        except Exception as e:
            # Track consecutive failures — force ghost-close after 3 to prevent
            # positions bleeding forever when exchange rejects sells
            count = self._exit_failure_count.get(pos.id, 0) + 1
            self._exit_failure_count[pos.id] = count
            if count >= 3:
                logger.warning(
                    f"[PM] FORCE GHOST-CLOSE {pos.symbol} ({reason}): "
                    f"{count} consecutive exit failures — closing as unsellable. "
                    f"Last error: {e}"
                )
                await self._cancel_exchange_sl(pos)
                # v7.7: reconcile PnL from actual exchange fills instead of current
                # price. Force_ghost was under-reporting PnL by using stale current
                # price when exchange had already closed position at SL fill price.
                _fallback = price if price > 0 else pos.entry_price
                (
                    _rec_pnl,
                    _rec_exit,
                    _rec_fees,
                    _from_fills,
                ) = await self._reconcile_exit_from_fills(pos, _fallback)
                if _from_fills:
                    pos.total_fees_usd += _rec_fees
                    pos.realized_pnl_usd = _rec_pnl
                    logger.info(
                        f"[PM] Force-ghost reconciled {pos.symbol}: exit≈${_rec_exit:.6f} "
                        f"PnL=${_rec_pnl:+.2f}"
                    )
                pos.status = "closed"
                pos.closed_at = int(time.time())
                pos.close_reason = f"{reason}_force_ghost"
                cooldown_until = time.time() + self.symbol_cooldown_minutes * 2 * 60
                self._symbol_cooldowns[pos.symbol] = cooldown_until
                closed = pos.to_dict()
                closed["exit_price"] = _rec_exit
                closed["pnl_pct"] = round(pos.current_pnl_pct(_rec_exit), 2)
                closed["pnl_usd"] = round(_rec_pnl, 4)
                self._closed_history.append(closed)
                if len(self._closed_history) > 200:
                    self._closed_history = self._closed_history[-200:]
                del self._positions[pos.id]
                self._exit_failure_count.pop(pos.id, None)
                active_positions.set(len(self._positions))
                return closed
            logger.error(
                f"[PM] Exit failed for {pos.symbol} ({reason}): {e} (attempt {count}/3)"
            )
            return None
        finally:
            self._positions_being_exited.discard(pos.id)

    async def _execute_partial_exit(
        self, pos: Position, price: float, reason: str, amount: float
    ) -> Optional[dict]:
        """Execute a partial position exit (tier exit)."""
        try:
            fill = await self.execution.exit_position(
                pos.symbol, amount, price, reason, direction=pos.side
            )
            if pos.side == "short":
                partial_pnl = (pos.entry_price - fill["filled_price"]) * fill[
                    "filled_amount"
                ]
            else:
                partial_pnl = (fill["filled_price"] - pos.entry_price) * fill[
                    "filled_amount"
                ]
            pos.realized_pnl_usd += partial_pnl
            pos.amount -= fill["filled_amount"]
            pos.amount_usd = pos.amount * pos.entry_price
            pos.total_fees_usd += fill.get("fee_usd", 0.0)

            logger.info(
                f"[PM] PARTIAL EXIT {pos.symbol} ({reason}): "
                f"sold={fill['filled_amount']:.6f} @ {fill['filled_price']:.6f} "
                f"partial_pnl=${partial_pnl:.2f}"
            )
            return {
                "type": "partial",
                "reason": reason,
                "symbol": pos.symbol,
                "pnl_usd": partial_pnl,
            }
        except Exception as e:
            logger.error(f"[PM] Partial exit failed for {pos.symbol} ({reason}): {e}")
            return None

    async def emergency_close_all(self, level: int = 3) -> list[dict]:
        """Graduated emergency close — not all-or-nothing.

        v7.3: 72 emergency_stop trades had 7% WR and -$988. Most were tiny losses
        (-0.1% to -0.5%) that didn't need emergency closing. Graduated levels:
          Level 1 (-8% day loss): close positions losing > 2% only
          Level 2 (-12% day loss): close positions losing > 1%
          Level 3 (-15% day loss): close everything (true emergency)
        Winning/breakeven positions keep running with tightened trailing stops.
        """
        results = []
        # Map level → PnL threshold. Level 3 = close everything (threshold=+999)
        _pnl_thresholds = {1: -2.0, 2: -1.0, 3: 999.0}
        _close_if_below = _pnl_thresholds.get(level, 999.0)

        for pos in list(self._positions.values()):
            if pos.status != "open":
                continue
            try:
                price = await self.execution.get_current_price(pos.symbol)
                pnl_pct = pos.current_pnl_pct(price)

                if level >= 3 or pnl_pct <= _close_if_below:
                    # Close this position
                    result = await self._execute_exit(
                        pos, price, "emergency_stop", pos.amount
                    )
                    if result:
                        results.append(result)
                elif pos.trailing_stop is None and pnl_pct > 0:
                    # Winning position without trail → activate trail now to protect gains
                    if pos.side == "long":
                        pos.trailing_stop = price * 0.995  # tight 0.5% trail
                    else:
                        pos.trailing_stop = price * 1.005
                    await self._update_exchange_sl(pos, pos.trailing_stop)
                    logger.info(
                        f"[PM] EMERGENCY TIGHTEN: {pos.symbol} +{pnl_pct:.1f}% → trail at {pos.trailing_stop:.6f}"
                    )
            except Exception as e:
                logger.error(f"[PM] Emergency close failed for {pos.symbol}: {e}")
        return results

    def get_open_positions(self) -> list[dict]:
        return [p.to_dict() for p in self._positions.values() if p.status == "open"]

    def get_closed_history(self, n: int = 50) -> list[dict]:
        return self._closed_history[-n:]

    def get_total_exposure_usd(self) -> float:
        return sum(p.amount_usd for p in self._positions.values() if p.status == "open")

    def get_bot_exposure_usd(self) -> float:
        """Exposure from bot-initiated trades only (excludes synced/exchange holdings).
        For futures positions, returns MARGIN (not notional) since leverage amplifies
        notional but the actual capital at risk is margin = notional / leverage."""
        return sum(
            p.margin_usd
            for p in self._positions.values()
            if p.status == "open"
            and p.setup_type not in ("synced_holding", "exchange_holding")
        )

    @property
    def has_failed_exits(self) -> bool:
        """True if any open position has 2+ consecutive exit failures.

        Was > 0 (one failure blocked ALL entries). Changed to >= 2 so the bot
        gets one retry cycle before locking out new entries. Ghost-close kicks
        in at 3 failures anyway, so the block window is at most 1-2 cycles.
        """
        return any(
            self._exit_failure_count.get(pos.id, 0) >= 2
            for pos in self._positions.values()
            if pos.status == "open"
        )

    def get_open_symbols(self) -> set[str]:
        return {p.symbol for p in self._positions.values() if p.status == "open"}

    def get_position_for_symbol(self, symbol: str) -> Optional["Position"]:
        """Return the first open position for a given symbol, or None."""
        for pos in self._positions.values():
            if pos.status == "open" and pos.symbol == symbol:
                return pos
        return None

    async def scale_position(
        self,
        pos: "Position",
        target_usd: float,
        current_price: float,
        tolerance_pct: float = 10.0,
    ) -> str:
        """Scale an existing position toward a target USD size instead of sell+rebuy.

        Returns one of:
          "hold"       — size is within tolerance, no trade executed
          "scaled_up"  — bought delta to reach target size
          "scaled_down"— sold delta to reach target size
          "error"      — trade attempt failed
        """
        if current_price <= 0 or pos.amount_usd <= 0:
            return "hold"

        # Revalue position at current market price for an apples-to-apples comparison
        current_value_usd = pos.amount * current_price

        # Guard: don't scale a dust position — let _tick_position ghost-close it naturally.
        # Scaling into dust would immediately re-open a full position that just stopped out.
        if current_value_usd < 5.0:
            logger.info(
                f"[PM] SCALE SKIP {pos.symbol}: position is dust "
                f"(${current_value_usd:.2f}) — awaiting natural close"
            )
            return "hold"

        delta_usd = target_usd - current_value_usd
        tolerance_usd = current_value_usd * (tolerance_pct / 100.0)

        if abs(delta_usd) <= tolerance_usd:
            logger.info(
                f"[PM] SCALE HOLD {pos.symbol}: "
                f"current=${current_value_usd:.2f} target=${target_usd:.2f} "
                f"delta=${delta_usd:+.2f} (within {tolerance_pct:.0f}% tolerance)"
            )
            return "hold"

        if delta_usd > 0:
            # Safety: never pyramid into a losing position — only scale up when
            # price is at or above entry (i.e., position is breakeven or profitable).
            if current_price < pos.entry_price * 0.998:
                logger.info(
                    f"[PM] SCALE BLOCKED {pos.symbol}: "
                    f"price {current_price:.6f} below entry {pos.entry_price:.6f} "
                    f"— refusing to pyramid into losing position"
                )
                return "hold"

            # Cap scale-ups at 2 per position to prevent runaway exposure.
            if pos.pyramid_count >= 2:
                logger.info(
                    f"[PM] SCALE BLOCKED {pos.symbol}: "
                    f"pyramid_count={pos.pyramid_count} at max (2) — no more adds"
                )
                return "hold"

            # Block scale-up if total position would exceed exchange max_qty.
            # This prevents accumulated positions from breaking SL placement and exits.
            fc = self._get_futures_exchange()
            if fc is not None:
                market = fc.exchange.markets.get(pos.symbol)
                if market:
                    max_qty = market.get("limits", {}).get("amount", {}).get("max")
                    if not max_qty:
                        for f in market.get("info", {}).get("filters") or []:
                            if f.get("filterType") in ("MARKET_LOT_SIZE", "LOT_SIZE"):
                                _mq = float(f.get("maxQty", 0))
                                if _mq > 0:
                                    max_qty = _mq
                                    break
                    if max_qty:
                        delta_amount = (
                            delta_usd / current_price if current_price > 0 else 0
                        )
                        new_total = pos.amount + delta_amount
                        if new_total > max_qty * 0.90:
                            logger.warning(
                                f"[PM] SCALE BLOCKED {pos.symbol}: "
                                f"new total {new_total:.2f} would exceed 90% of max_qty {max_qty:.2f} "
                                f"— preventing accumulation that breaks SL/exits"
                            )
                            return "hold"

            # Safety: block scale-up if price is at or near the stop_loss level.
            # Buying here would trigger an immediate stop_loss exit next tick.
            if pos.stop_loss > 0 and current_price <= pos.stop_loss * 1.005:
                logger.info(
                    f"[PM] SCALE BLOCKED {pos.symbol}: "
                    f"price {current_price:.6f} at/near stop_loss {pos.stop_loss:.6f} "
                    f"— skipping scale_up to avoid immediate stop cycle"
                )
                return "hold"

            # Need to buy more — buy only the delta
            try:
                # Pass leverage/direction for futures mode (FuturesExecutionCore)
                extra_kwargs = {}
                if hasattr(pos, "leverage") and pos.leverage > 1:
                    extra_kwargs["leverage"] = pos.leverage
                    extra_kwargs["direction"] = pos.side or "long"
                fill = await self.execution.enter_position(
                    symbol=pos.symbol,
                    side="buy" if pos.side != "short" else "sell",
                    amount_usd=delta_usd,
                    price=current_price,
                    setup_type="scale_up",
                    **extra_kwargs,
                )
                filled_amount = float(fill.get("filled_amount", 0.0))
                if filled_amount > 0:
                    old_entry = pos.entry_price  # capture before updating
                    total_amount = pos.amount + filled_amount
                    # Weighted average entry price
                    pos.entry_price = (
                        old_entry * pos.amount + current_price * filled_amount
                    ) / total_amount
                    pos.amount = total_amount
                    pos.amount_usd += float(fill.get("amount_usd", delta_usd))
                    pos.total_fees_usd += fill.get("fee_usd", 0.0)
                    # Update stop_loss proportionally so it trails the new entry price.
                    # Preserves the original risk-distance fraction set at open_position.
                    if pos.stop_loss > 0 and old_entry > 0:
                        sl_dist_frac = (old_entry - pos.stop_loss) / old_entry
                        pos.stop_loss = pos.entry_price * (1.0 - sl_dist_frac)
                    if current_price > pos.highest_price:
                        pos.highest_price = current_price
                    pos.pyramid_count += 1
                    logger.info(
                        f"[PM] SCALE UP {pos.symbol}: "
                        f"+{filled_amount:.6f} @ {current_price:.6f} "
                        f"(delta=${delta_usd:.2f}) new_total={pos.amount:.6f} "
                        f"new_entry={pos.entry_price:.6f} new_sl={pos.stop_loss:.6f} "
                        f"pyramid={pos.pyramid_count}/2"
                    )
                    # Update exchange SL to reflect new amount and SL price.
                    # Without this, old stop has stale amount → partial protection.
                    _eff_stop = (
                        pos.trailing_stop
                        if (pos.trailing_stop and pos.trailing_stop > pos.stop_loss)
                        else pos.stop_loss
                    )
                    await self._update_exchange_sl(pos, _eff_stop)
                return "scaled_up"
            except Exception as e:
                logger.error(f"[PM] Scale-up failed for {pos.symbol}: {e}")
                return "error"
        else:
            # SCALE-DOWN DISABLED — data shows it destroys value:
            #   CRV: opened $325, sold $310 of it 45 seconds later (fee + spread loss)
            #   BNB: 4 consecutive scale_downs turning $622 into dust
            # Positions exit via stop_loss / trailing / time_exit, NOT gradual trimming.
            # Re-computing size every cycle with different multipliers (drawdown, regime,
            # conviction) causes constant delta oscillations → churn → fees → death.
            logger.debug(
                f"[PM] SCALE SKIP DOWN {pos.symbol}: "
                f"current=${current_value_usd:.2f} target=${target_usd:.2f} "
                f"delta=${delta_usd:+.2f} — scale_down disabled"
            )
            return "hold"

    @property
    def open_count(self) -> int:
        return len([p for p in self._positions.values() if p.status == "open"])

    def get_all_positions(self) -> list[Position]:
        """Return all currently-open Position objects (not dicts).

        Introduced for the v7.5 BTC_CRASH_SWEEP loop in backend/server.py which
        needs Position instances (to call `.current_pnl_pct()` / `.symbol`).
        The existing `get_open_positions()` returns dicts and isn't compatible.
        Excludes ghost/closed rows so callers never operate on stale state.
        """
        return [
            p
            for p in self._positions.values()
            if p.status == "open" and p.amount_usd > 0.10
        ]

    @property
    def bot_open_count(self) -> int:
        """Count of bot-initiated positions only (excludes synced/exchange holdings)."""
        return len(
            [
                p
                for p in self._positions.values()
                if p.status == "open"
                and p.setup_type not in ("synced_holding", "exchange_holding")
                and p.amount_usd > 0.10
            ]
        )
