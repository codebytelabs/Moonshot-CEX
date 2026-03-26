"""
PositionManager — Full position lifecycle management.
Tracks open positions, manages tier exits, trailing stops, pyramiding, and time exits.
"""
import time
import uuid
from typing import Optional
from loguru import logger

from .execution_core import ExecutionCore, SubMinimumAmountError
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

        self.status = "open"
        self.highest_price = entry_price
        self.lowest_price = entry_price
        self.trailing_stop: Optional[float] = None
        self.tier1_done = False
        self.tier2_done = False
        self.pyramid_count = 0

        self.realized_pnl_usd = 0.0
        self.total_fees_usd = entry_fill.get("fee_usd", 0.0) if entry_fill else 0.0

        self.opened_at = int(time.time())
        self.closed_at: Optional[int] = None
        self.close_reason: Optional[str] = None

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
        self.momentum_recheck_interval_minutes = max(1, momentum_recheck_interval_minutes)
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

    def is_symbol_on_cooldown(self, symbol: str) -> bool:
        """True if this symbol was recently stopped out and is still cooling down."""
        expires_at = self._symbol_cooldowns.get(symbol)
        if expires_at is None:
            return False
        if time.time() < expires_at:
            return True
        del self._symbol_cooldowns[symbol]
        return False

    def is_symbol_churning(self, symbol: str, window_hours: float = 4.0, max_entries: int = 3) -> bool:
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
            return pos
        except Exception as e:
            logger.warning(f"[PM] restore_position_from_dict failed: {e} | doc={doc.get('symbol', '?')}")
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
        stop_loss = float(entry_zone.get("stop_loss", price * 0.94))  # fallback: 6% below entry

        if price <= 0:
            logger.warning(f"[PM] Skipping {symbol}: invalid price {price}")
            return None

        risk_per_unit = price - stop_loss
        take_profit_1 = price + tier1_r * risk_per_unit
        take_profit_2 = price + tier2_r * risk_per_unit

        try:
            fill = await self.execution.enter_position(
                symbol=symbol,
                side="buy",
                amount_usd=amount_usd,
                price=price,
                setup_type=setup.get("setup_type", "unknown"),
            )
        except Exception as e:
            logger.error(f"[PM] Entry failed for {symbol}: {e}")
            return None

        fill_price = fill["filled_price"]
        fill_amount = fill["filled_amount"]

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
            side="long", # Only long supported for now
        )
        self._positions[pos.id] = pos
        self._record_entry(symbol)
        active_positions.set(len(self._positions))
        logger.info(
            f"[PM] OPENED {symbol} {pos.side} id={pos.id} "
            f"entry={fill_price:.6f} sl={stop_loss:.6f} "
            f"tp1={take_profit_1:.6f} amount=${fill['amount_usd']:.2f}"
        )
        return pos

    async def pyramid_add(self, pos: Position, current_price: float, add_usd: float) -> bool:
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
        pos.entry_price = (pos.entry_price * pos.amount + current_price * filled_amount) / total_amount
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
            result = await self._tick_position(pos, regime_params)
            if result:
                exits.append(result)
        return exits

    async def sweep_vulnerable_positions(self) -> list[Optional[dict]]:
        """
        Called when regime suddenly shifts to bear or choppy.
        Sweeps through existing bot positions and aggressively closes those 
        that aren't solidly in profit (e.g. < 0.5% profit).
        """
        exits = []
        for pos_id, pos in list(self._positions.items()):
            if pos.id in self._positions_being_exited:
                continue
            if pos.setup_type in ("synced_holding", "exchange_holding"):
                continue # Leave manual holdings alone
            
            try:
                current_price = await self.execution.get_current_price(pos.symbol)
                if current_price <= 0:
                    continue
                pnl_pct = pos.current_pnl_pct(current_price)
                if pnl_pct < 0.5:
                    logger.warning(f"[PM] Regime shift sweep: closing {pos.symbol} (PnL {pnl_pct:.2f}%) to protect capital")
                    result = await self._execute_exit(pos, current_price, "regime_shift_sweep", pos.amount)
                    exits.append(result)
            except Exception as e:
                logger.debug(f"[PM] Sweep error for {pos.symbol}: {e}")
        return exits

    def _momentum_exit_reason(self, pos: Position, current_price: float, pnl_pct: float, regime_params: Optional[dict]) -> Optional[str]:
        """Simplified momentum exit — DATA-DRIVEN OVERHAUL.

        Analysis of 37 real trades showed:
          - momentum_died / no_traction / stall exits: 0% win rate, -$884 total
          - trailing_stop: 100% win rate, only profitable exit
          - momentum_died_20m: 100% win rate (most patient = most profitable)

        New design: ONLY exit on momentum_faded (gave back huge peak).
        Everything else is handled by: stop_loss → trailing_stop → time_exit.
        The old 7+ momentum exits were killing winners before trailing could activate.
        """
        hold_minutes = pos.hold_time_hours() * 60.0
        peak_pnl_pct = pos.current_pnl_pct(pos.highest_price if pos.side == "long" else pos.lowest_price)
        giveback_pct = peak_pnl_pct - pnl_pct

        # Momentum faded: had a significant peak (+3%+) but gave back 70%+ of gains.
        # This is the ONE justified momentum exit — don't let a +5% winner turn into -2% loser.
        if hold_minutes >= 30 and peak_pnl_pct >= 3.0 and giveback_pct >= max(peak_pnl_pct * 0.6, 2.0) and pnl_pct < 0.5:
            return "momentum_faded"

        return None

    async def _tick_position(self, pos: Position, regime_params: Optional[dict]) -> Optional[dict]:
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

        sl_pct = regime_params.get("stop_loss_pct", self.stop_loss_pct) if regime_params else self.stop_loss_pct
        trail_activate = regime_params.get("trailing_activate_pct", self.trailing_activate_pct) if regime_params else self.trailing_activate_pct
        trail_dist = regime_params.get("trailing_distance_pct", self.trailing_distance_pct) if regime_params else self.trailing_distance_pct
        effective_time_exit_hours = regime_params.get("time_exit_hours", self.time_exit_hours) if regime_params else self.time_exit_hours

        pnl_pct = pos.current_pnl_pct(current_price)
        r_multiple = pos.current_r_multiple(current_price)

        # Update dynamic stop loss — always ensure SL reflects configured percentage minimum
        abs_sl_pct = abs(sl_pct) / 100.0
        dynamic_sl = pos.entry_price * (1 - abs_sl_pct) if pos.side == "long" else pos.entry_price * (1 + abs_sl_pct)
        
        # For synced/exchange holdings with no stop loss, apply config-based SL
        # For bot positions, keep the tighter of: TA-based SL vs config-based SL
        if pos.stop_loss <= 0:
            pos.stop_loss = dynamic_sl
        elif pos.setup_type in ("synced_holding", "exchange_holding"):
            if pos.side == "long":
                pos.stop_loss = max(pos.stop_loss, dynamic_sl)
            else:
                pos.stop_loss = min(pos.stop_loss, dynamic_sl) if pos.stop_loss > 0 else dynamic_sl

        # Trailing stop management
        if pnl_pct >= trail_activate:
            trail_price = pos.highest_price * (1 - trail_dist / 100.0)
            if pos.trailing_stop is None or trail_price > pos.trailing_stop:
                pos.trailing_stop = trail_price

        # ── Exit checks ──────────────────────────────────────────────────

        if pos.id in self._positions_being_exited:
            return None

        is_synced = pos.setup_type in ("synced_holding", "exchange_holding")

        # Hard stop loss — always applies
        if (pos.side == "long" and current_price <= pos.stop_loss) or (pos.side == "short" and current_price >= pos.stop_loss) or pnl_pct <= sl_pct:
            return await self._execute_exit(pos, current_price, "stop_loss", pos.amount)

        # Trailing stop — always applies
        if pos.trailing_stop and ((pos.side == "long" and current_price <= pos.trailing_stop) or (pos.side == "short" and current_price >= pos.trailing_stop)):
            return await self._execute_exit(pos, current_price, "trailing_stop", pos.amount)

        hold_h = pos.hold_time_hours()

        # ── Bot-only: momentum_faded exit (the ONE justified momentum exit) ───
        # Data: all early momentum kills (died/stall/traction) had 0% win rate
        # and destroyed -$884 across 37 trades. Only momentum_faded (giving back
        # huge peaks) and trailing_stop (100% wr) were profitable.
        # The stop_loss (-3.5%) protects downside. Trailing (+1% activate) rides winners.
        # Time exit (2h) cleans up dead trades. No other momentum exits needed.
        if not is_synced:
            momentum_reason = self._momentum_exit_reason(pos, current_price, pnl_pct, regime_params)
            if momentum_reason:
                return await self._execute_exit(pos, current_price, momentum_reason, pos.amount)

        # Time exit — ONLY for losing positions. If green, the wave is working → let
        # trailing handle the exit. Data: 32/52 trades died on time_exit clock at -$2 avg.
        # Many were in profit but killed before trailing activated. Wave riding means
        # HOLDING winners, not ejecting on a timer.
        if hold_h >= effective_time_exit_hours and pnl_pct <= 0:
            return await self._execute_exit(pos, current_price, "time_exit", pos.amount)
        # Safety cap: even profitable positions get a hard ceiling at 2× time limit
        # to prevent zombie positions that never trigger trailing.
        if hold_h >= effective_time_exit_hours * 2:
            return await self._execute_exit(pos, current_price, "time_exit_max", pos.amount)

        # Tier 1 (partial exit at 2R)
        if not pos.tier1_done and r_multiple >= 2.0:
            tier1_amount = pos.amount * self.tier1_exit_pct
            result = await self._execute_partial_exit(pos, current_price, "tier1", tier1_amount)
            pos.tier1_done = True
            # Tighten trailing stop after T1
            if pos.trailing_stop:
                tighter = pos.highest_price * (1 - (trail_dist * 0.75) / 100.0)
                pos.trailing_stop = max(pos.trailing_stop, tighter)
            if result:
                return result

        # Tier 2 (partial exit at 5R)
        if pos.tier1_done and not pos.tier2_done and r_multiple >= 5.0:
            tier2_amount = pos.amount * self.tier2_exit_pct
            result = await self._execute_partial_exit(pos, current_price, "tier2", tier2_amount)
            pos.tier2_done = True
            if result:
                return result

        # Pyramid add — add to a winner when R ≥ pyramid_min_r
        if self.pyramid_enabled and r_multiple >= self.pyramid_min_r and pos.pyramid_count < self.pyramid_max_adds:
            # Add 50% of original position size
            add_usd = pos.amount_usd * 0.5
            if add_usd >= 5.0:  # minimum sensible add
                await self.pyramid_add(pos, current_price, add_usd)

        return None


    async def _execute_exit(self, pos: Position, price: float, reason: str, amount: float) -> Optional[dict]:
        """Execute a full position exit."""
        if pos.id in self._positions_being_exited:
            return None
        self._positions_being_exited.add(pos.id)
        try:
            fill = await self.execution.exit_position(pos.symbol, amount, price, reason)
            filled_amount = float(fill.get("filled_amount") or 0.0)  # type: ignore[arg-type]
            if filled_amount < amount * 0.999:
                if pos.side == "short":
                    partial_pnl = (pos.entry_price - fill["filled_price"]) * filled_amount
                else:
                    partial_pnl = (fill["filled_price"] - pos.entry_price) * filled_amount
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
                if any(x in r for x in ("stop", "momentum", "time_exit", "regime", "hard_loss", "no_traction", "emergency", "faded", "stall")):
                    cooldown_m = self.symbol_cooldown_minutes * (1.5 if "stop" in r else 1.0)
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
                final_tranche_pnl = (pos.entry_price - fill["filled_price"]) * filled_amount
            else:
                final_tranche_pnl = (fill["filled_price"] - pos.entry_price) * filled_amount
            pos.realized_pnl_usd += final_tranche_pnl
            pos.total_fees_usd += fill.get("fee_usd", 0.0)
            pos.status = "closed"
            pos.closed_at = int(time.time())
            pos.close_reason = reason

            pnl_usd = pos.realized_pnl_usd  # cumulative: tier1 + tier2 + final tranche
            if pos.side == "short":
                pnl_pct = (pos.entry_price - fill["filled_price"]) / pos.entry_price * 100.0
            else:
                pnl_pct = (fill["filled_price"] - pos.entry_price) / pos.entry_price * 100.0

            logger.info(
                f"[PM] CLOSED {pos.symbol} ({reason}): "
                f"pnl=${pnl_usd:.2f} ({pnl_pct:+.1f}%) "
                f"hold={pos.hold_time_hours():.1f}h"
            )

            closed = pos.to_dict()
            closed["exit_price"] = fill["filled_price"]
            closed["pnl_pct"] = round(pnl_pct, 2)
            closed["pnl_usd"] = round(pos.realized_pnl_usd, 4)  # required by server.py DB update check
            self._closed_history.append(closed)
            if len(self._closed_history) > 200:
                self._closed_history = self._closed_history[-200:]

            # ── Tiered cooldown by exit reason ────────────────────────────────
            # Danger exits (stop, regime sweep) → 45 min: coin is in trouble.
            # Momentum/time failures → 20-30 min: setup failed, give it a reset.
            # TP / trailing → 5-10 min: profitable exit, fresh signal may re-enter.
            # momentum_faded is the only momentum exit now (full close, not scale-down).
            r = reason.lower()
            if any(x in r for x in ("stop_loss", "regime_shift", "emergency")):
                cooldown_m = self.symbol_cooldown_minutes * 1.5   # 45 min
            elif any(x in r for x in ("no_traction", "time_exit")):
                cooldown_m = self.symbol_cooldown_minutes          # 30 min
            elif any(x in r for x in ("faded", "died", "stall")):
                cooldown_m = self.symbol_cooldown_minutes * 0.67   # 20 min
            elif "trailing" in r:
                cooldown_m = max(8.0, self.symbol_cooldown_minutes * 0.33)  # 10 min
            elif any(x in r for x in ("tp", "take_profit", "tier1", "tier2")):
                cooldown_m = max(5.0, self.symbol_cooldown_minutes * 0.2)   # 6 min
            else:
                cooldown_m = self.symbol_cooldown_minutes          # 30 min default
            cooldown_until = time.time() + cooldown_m * 60
            self._symbol_cooldowns[pos.symbol] = cooldown_until
            logger.info(f"[PM] Cooldown {pos.symbol} for {cooldown_m:.0f}m after {reason}")

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
            closed["pnl_usd"] = round(pos.realized_pnl_usd, 4)  # required by server.py DB update check
            self._closed_history.append(closed)
            if len(self._closed_history) > 200:
                self._closed_history = self._closed_history[-200:]
            del self._positions[pos.id]
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
                pos.status = "closed"
                pos.closed_at = int(time.time())
                pos.close_reason = f"{reason}_force_ghost"
                cooldown_until = time.time() + self.symbol_cooldown_minutes * 2 * 60
                self._symbol_cooldowns[pos.symbol] = cooldown_until
                closed = pos.to_dict()
                closed["exit_price"] = price if price > 0 else pos.entry_price
                closed["pnl_pct"] = round(pos.current_pnl_pct(closed["exit_price"]), 2)
                closed["pnl_usd"] = round(pos.unrealized_pnl_usd(closed["exit_price"]), 4)
                self._closed_history.append(closed)
                if len(self._closed_history) > 200:
                    self._closed_history = self._closed_history[-200:]
                del self._positions[pos.id]
                self._exit_failure_count.pop(pos.id, None)
                active_positions.set(len(self._positions))
                return closed
            logger.error(f"[PM] Exit failed for {pos.symbol} ({reason}): {e} (attempt {count}/3)")
            return None
        finally:
            self._positions_being_exited.discard(pos.id)


    async def _execute_partial_exit(self, pos: Position, price: float, reason: str, amount: float) -> Optional[dict]:
        """Execute a partial position exit (tier exit)."""
        try:
            fill = await self.execution.exit_position(pos.symbol, amount, price, reason)
            partial_pnl = (fill["filled_price"] - pos.entry_price) * fill["filled_amount"]
            pos.realized_pnl_usd += partial_pnl
            pos.amount -= fill["filled_amount"]
            pos.amount_usd = pos.amount * pos.entry_price
            pos.total_fees_usd += fill.get("fee_usd", 0.0)

            logger.info(
                f"[PM] PARTIAL EXIT {pos.symbol} ({reason}): "
                f"sold={fill['filled_amount']:.6f} @ {fill['filled_price']:.6f} "
                f"partial_pnl=${partial_pnl:.2f}"
            )
            return {"type": "partial", "reason": reason, "symbol": pos.symbol, "pnl_usd": partial_pnl}
        except Exception as e:
            logger.error(f"[PM] Partial exit failed for {pos.symbol} ({reason}): {e}")
            return None

    async def emergency_close_all(self) -> list[dict]:
        """Close all open positions immediately (emergency stop)."""
        results = []
        for pos in list(self._positions.values()):
            if pos.status == "open":
                try:
                    price = await self.execution.get_current_price(pos.symbol)
                    result = await self._execute_exit(pos, price, "emergency_stop", pos.amount)
                    if result:
                        results.append(result)
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
        """Exposure from bot-initiated trades only (excludes synced/exchange holdings)."""
        return sum(
            p.amount_usd for p in self._positions.values()
            if p.status == "open" and p.setup_type not in ("synced_holding", "exchange_holding")
        )

    @property
    def has_failed_exits(self) -> bool:
        """True if any open position has accumulated exit failures."""
        return any(
            self._exit_failure_count.get(pos.id, 0) > 0
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
                fill = await self.execution.enter_position(
                    symbol=pos.symbol,
                    side="buy",
                    amount_usd=delta_usd,
                    price=current_price,
                    setup_type="scale_up",
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

    @property
    def bot_open_count(self) -> int:
        """Count of bot-initiated positions only (excludes synced/exchange holdings)."""
        return len([
            p for p in self._positions.values()
            if p.status == "open"
            and p.setup_type not in ("synced_holding", "exchange_holding")
            and p.amount_usd > 0.10
        ])
