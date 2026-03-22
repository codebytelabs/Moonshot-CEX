"""
ExecutionCore — CEX order placement and fill tracking.
Handles market/limit orders via CCXT with retry, slippage tracking, and paper mode.
"""
import time
import asyncio
from typing import Optional
from loguru import logger

from .exchange_ccxt import ExchangeConnector
from .metrics import trades_total, errors_total


class SubMinimumAmountError(Exception):
    """Raised when an exit amount is below the exchange's minimum lot size.
    PositionManager should catch this and ghost-close the position (clear from
    internal tracking without placing an order, since the coins are already dust).
    """
    def __init__(self, symbol: str, amount: float, min_amount: float, price: float, reason: str):
        self.symbol = symbol
        self.amount = amount
        self.min_amount = min_amount
        self.price = price
        self.reason = reason
        super().__init__(
            f"{symbol} exit amount {amount:.8f} < exchange minimum {min_amount:.8f} (dust)"
        )

class ExecutionCore:
    """Order execution with retry and paper trading support."""

    def __init__(
        self,
        exchange: ExchangeConnector,
        exchange_mode: str = "paper",
        max_retries: int = 3,
        exit_limit_poll_seconds: int = 3,
        exit_limit_initial_markup_bps: float = 8.0,
        exit_limit_reprice_step_bps: float = 6.0,
        exit_limit_final_cross_bps: float = 2.0,
    ):
        self.exchange = exchange
        self.mode = exchange_mode
        self.max_retries = max_retries
        self.exit_limit_poll_seconds = exit_limit_poll_seconds
        self.exit_limit_initial_markup_bps = exit_limit_initial_markup_bps
        self.exit_limit_reprice_step_bps = exit_limit_reprice_step_bps
        self.exit_limit_final_cross_bps = exit_limit_final_cross_bps
        self._paper_fill_counter = 0

    async def enter_position(
        self,
        symbol: str,
        side: str,
        amount_usd: float,
        price: float,
        setup_type: str = "unknown",
    ) -> dict:
        """
        Execute a position entry.
        Returns fill result dict with filled_price, filled_amount, fee_usd, order_id.
        """
        if self.mode == "paper":
            return self._paper_fill(symbol, side, amount_usd, price, "entry", setup_type)

        amount = self.exchange.cost_to_amount(symbol, amount_usd, price)
        if amount <= 0:
            raise ValueError(f"Invalid amount {amount} for {symbol} at {price}")

        for attempt in range(self.max_retries):
            try:
                # Timeout wrapper to prevent hanging on slow testnet orders
                if side == "buy":
                    order = await asyncio.wait_for(
                        self.exchange.create_market_buy(symbol, amount, price),
                        timeout=30.0
                    )
                else:
                    order = await asyncio.wait_for(
                        self.exchange.create_market_sell(symbol, amount),
                        timeout=30.0
                    )

                fill = await asyncio.wait_for(
                    self._poll_fill(symbol, order["id"]),
                    timeout=30.0
                )
                fill_price = fill.get("average") or fill.get("price") or price
                raw_filled = fill.get("filled")
                # Gate.io testnet returns 'filled' as quote cost (USDT) not base coin amount.
                # Detect: if raw_filled >> sent amount, it's USDT cost — divide by fill_price.
                if raw_filled is not None and fill_price and raw_filled > amount * 2:
                    filled_amount = raw_filled / fill_price
                else:
                    filled_amount = raw_filled if raw_filled is not None else amount
                fee = fill.get("fee", {}) or {}
                fee_cost = float(fee.get("cost", 0.0))
                fee_currency = fee.get("currency", "USDT")
                fee_usd = fee_cost if fee_currency == "USDT" else fee_cost * fill_price

                trades_total.labels(side=side, exchange=self.exchange.name).inc()
                logger.info(
                    f"[Exec] FILLED {side.upper()} {symbol}: "
                    f"amount={filled_amount:.6f} @ {fill_price:.6f} fee=${fee_usd:.4f}"
                )
                return {
                    "order_id": order["id"],
                    "symbol": symbol,
                    "side": side,
                    "filled_price": fill_price,
                    "filled_amount": filled_amount,
                    "amount_usd": fill_price * filled_amount,
                    "fee_usd": fee_usd,
                    "slippage_pct": (fill_price - price) / price * 100 if price else 0.0,
                    "timestamp": int(time.time()),
                    "mode": self.mode,
                }

            except Exception as e:
                logger.warning(f"[Exec] Entry attempt {attempt+1} failed for {symbol}: {e}")
                errors_total.labels(component="execution", error_type="order_failed").inc()
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        raise Exception(f"Order entry failed after {self.max_retries} attempts for {symbol}")

    async def exit_position(
        self,
        symbol: str,
        amount: float,
        price: float,
        reason: str = "exit",
    ) -> dict:
        """Execute a position exit (sell)."""
        if self.mode == "paper":
            return self._paper_fill(symbol, "sell", amount * price, price, reason)

        # Resolve actual available balance to avoid BALANCE_NOT_ENOUGH from rounding/fees
        base_currency = symbol.split("/")[0]
        try:
            balance = await self.exchange.fetch_balance()
            available = float(balance.get(base_currency, {}).get("free", 0) or 0)
            if available <= 0:
                raise ValueError(f"No {base_currency} balance available to sell")
            # Use the smaller of tracked amount and available, with 0.5% safety buffer
            safe_amount = min(amount, available * 0.995)
        except ValueError:
            raise
        except Exception:
            safe_amount = amount  # fallback to tracked amount if balance fetch fails

        # ── Minimum lot size guard ──────────────────────────────────────────
        # Gate.io (and most exchanges) enforce TWO minimums:
        #   1. min amount (base coin qty)  e.g. 0.001 ETH
        #   2. min cost   (USDT notional)  e.g. 3 USDT
        # If either is violated raise SubMinimumAmountError → ghost-close.
        try:
            market = self.exchange._exchange.market(symbol)  # type: ignore[attr-defined]
            limits = market.get("limits") or {}
            min_amount = float(limits.get("amount", {}).get("min") or 0)
            min_cost   = float(limits.get("cost",   {}).get("min") or 0)
            notional   = safe_amount * price

            violated = False
            min_val   = min_amount
            if min_amount > 0 and safe_amount < min_amount:
                violated = True
            elif min_cost > 0 and notional < min_cost:
                violated = True
                min_val = min_cost  # report in USDT terms

            if violated:
                logger.warning(
                    f"[Exec] {symbol} amount {safe_amount:.8f} (${notional:.4f}) "
                    f"< exchange minimum. Ghost-closing position (dust)."
                )
                raise SubMinimumAmountError(
                    symbol=symbol,
                    amount=safe_amount,
                    min_amount=min_val,
                    price=price,
                    reason=reason,
                )
        except SubMinimumAmountError:
            raise
        except Exception as e:
            logger.debug(f"[Exec] Could not fetch market limits for {symbol}: {e}")
        # ───────────────────────────────────────────────────────────────────


        amount_adj = self.exchange.amount_to_precision(symbol, safe_amount)
        if amount_adj <= 0:
            raise ValueError(f"Invalid sell amount {amount_adj} for {symbol}")


        total_filled_amount = 0.0
        total_filled_usd = 0.0
        total_fee_usd = 0.0

        for attempt in range(self.max_retries):
            try:
                remaining_amount = self.exchange.amount_to_precision(symbol, amount_adj - total_filled_amount)
                if remaining_amount <= 0:
                    break
                limit_price = await self._compute_exit_limit_price(symbol, price, attempt)
                order = await asyncio.wait_for(
                    self.exchange.create_limit_sell(symbol, remaining_amount, limit_price),
                    timeout=30.0
                )
                fill = await asyncio.wait_for(
                    self._poll_fill(symbol, order["id"], max_polls=self.exit_limit_poll_seconds),
                    timeout=30.0
                )
                latest = fill
                if latest.get("status") not in ("closed", "filled"):
                    latest = await self.exchange.fetch_order(order["id"], symbol)
                    if latest.get("status") not in ("closed", "filled"):
                        try:
                            await self.exchange.cancel_order(order["id"], symbol)
                        except Exception as cancel_error:
                            logger.warning(f"[Exec] Cancel failed for {symbol} order {order['id']}: {cancel_error}")
                fill_price, filled_amount, fee_usd = self._parse_fill(symbol, latest, limit_price, remaining_amount)
                if filled_amount > 0:
                    total_filled_amount += filled_amount
                    total_filled_usd += fill_price * filled_amount
                    total_fee_usd += fee_usd
                if total_filled_amount >= amount_adj * 0.999:
                    avg_price = total_filled_usd / total_filled_amount if total_filled_amount > 0 else price
                    trades_total.labels(side="sell", exchange=self.exchange.name).inc()
                    logger.info(
                        f"[Exec] SOLD {symbol} ({reason}): "
                        f"amount={total_filled_amount:.6f} @ {avg_price:.6f}"
                    )
                    return {
                        "order_id": order["id"],
                        "symbol": symbol,
                        "side": "sell",
                        "filled_price": avg_price,
                        "filled_amount": total_filled_amount,
                        "amount_usd": total_filled_usd,
                        "fee_usd": total_fee_usd,
                        "reason": reason,
                        "timestamp": int(time.time()),
                        "mode": self.mode,
                    }

            except SubMinimumAmountError:
                raise  # propagate ghost-close signal immediately
            except Exception as e:
                err_str = str(e).lower()
                # ── Second-layer dust detection ──────────────────────────────
                # Gate.io and other exchanges return human-readable "too small"
                # errors when amount OR notional is below their minimums.
                # Detect these patterns and convert to SubMinimumAmountError so
                # PositionManager ghost-closes instead of retrying 5 times.
                dust_patterns = (
                    "too small",
                    "minimum amount",
                    "minimum is",
                    "amount of",
                    "order size",
                    "less than min",
                    "below minimum",
                    "invalid_param_value",  # Gate.io size error code
                )
                if any(p in err_str for p in dust_patterns):
                    logger.warning(
                        f"[Exec] {symbol} dust detected from exchange error: {e}. "
                        f"Ghost-closing."
                    )
                    raise SubMinimumAmountError(
                        symbol=symbol,
                        amount=amount_adj,
                        min_amount=0.0,  # unknown, exchange message has it
                        price=price,
                        reason=reason,
                    )
                # ─────────────────────────────────────────────────────────────
                logger.warning(f"[Exec] Exit attempt {attempt+1} failed for {symbol}: {e}")
                errors_total.labels(component="execution", error_type="sell_failed").inc()
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)


        if total_filled_amount > 0:
            avg_price = total_filled_usd / total_filled_amount if total_filled_amount > 0 else price
            trades_total.labels(side="sell", exchange=self.exchange.name).inc()
            logger.info(
                f"[Exec] SOLD {symbol} ({reason}): "
                f"amount={total_filled_amount:.6f} @ {avg_price:.6f}"
            )
            return {
                "order_id": f"partial_exit_{int(time.time())}",
                "symbol": symbol,
                "side": "sell",
                "filled_price": avg_price,
                "filled_amount": total_filled_amount,
                "amount_usd": total_filled_usd,
                "fee_usd": total_fee_usd,
                "reason": reason,
                "timestamp": int(time.time()),
                "mode": self.mode,
            }

        raise Exception(f"Exit failed after {self.max_retries} attempts for {symbol}")

    async def _compute_exit_limit_price(self, symbol: str, reference_price: float, attempt: int) -> float:
        book = await self.exchange.fetch_order_book(symbol, limit=5)
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        best_bid = float(bids[0][0]) if bids else reference_price
        best_ask = float(asks[0][0]) if asks else reference_price
        if attempt <= 0:
            candidate = best_ask * (1 + self.exit_limit_initial_markup_bps / 10000.0)
        elif attempt >= self.max_retries - 1:
            candidate = best_bid * (1 - self.exit_limit_final_cross_bps / 10000.0)
        else:
            progress = attempt / max(1, self.max_retries - 1)
            upper = best_ask * (1 + self.exit_limit_initial_markup_bps / 10000.0)
            lower = best_bid * (1 - self.exit_limit_final_cross_bps / 10000.0)
            candidate = upper - (upper - lower) * progress
            candidate *= 1 - (self.exit_limit_reprice_step_bps / 10000.0) * attempt
        return self.exchange.price_to_precision(symbol, max(candidate, best_bid * 0.995))

    def _parse_fill(self, symbol: str, fill: dict, fallback_price: float, requested_amount: float) -> tuple[float, float, float]:
        fill_price = float(fill.get("average") or fill.get("price") or fallback_price or 0.0)
        raw_filled = fill.get("filled")
        if raw_filled is not None and fill_price and raw_filled > requested_amount * 2:
            filled_amount = raw_filled / fill_price
        else:
            filled_amount = float(raw_filled or 0.0)
        fee = fill.get("fee", {}) or {}
        fee_cost = float(fee.get("cost", 0.0))
        fee_currency = fee.get("currency", "USDT")
        fee_usd = fee_cost if fee_currency == "USDT" else fee_cost * fill_price
        return fill_price, self.exchange.amount_to_precision(symbol, filled_amount), fee_usd

    async def get_current_price(self, symbol: str) -> float:
        """Fetch latest price for a symbol."""
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            return float(ticker.get("last") or ticker.get("bid") or 0.0)
        except Exception as e:
            logger.debug(f"[Exec] Price fetch failed for {symbol}: {e}")
            return 0.0

    async def _poll_fill(self, symbol: str, order_id: str, max_polls: int = 10) -> dict:
        """Poll order status until filled."""
        for _ in range(max_polls):
            try:
                order = await self.exchange.fetch_order(order_id, symbol)
                status = order.get("status", "open")
                if status in ("closed", "filled"):
                    return order
                if status == "canceled":
                    raise Exception(f"Order {order_id} was canceled")
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.debug(f"[Exec] Poll error for {order_id}: {e}")
                await asyncio.sleep(1.0)
        return {"status": "unknown", "average": None, "filled": None, "fee": {}}

    def _paper_fill(
        self,
        symbol: str,
        side: str,
        amount_usd: float,
        price: float,
        reason: str = "entry",
        setup_type: str = "unknown",
    ) -> dict:
        """Simulate an order fill for paper trading."""
        self._paper_fill_counter += 1
        slippage = 0.001 if side == "buy" else -0.001
        fill_price = price * (1 + slippage)
        amount = amount_usd / fill_price if fill_price > 0 else 0.0
        fee_usd = amount_usd * 0.001

        trades_total.labels(side=side, exchange="paper").inc()
        logger.info(
            f"[Exec] PAPER {side.upper()} {symbol} ({reason}): "
            f"amount={amount:.6f} @ {fill_price:.6f} fee=${fee_usd:.4f}"
        )
        return {
            "order_id": f"paper_{self._paper_fill_counter}",
            "symbol": symbol,
            "side": side,
            "filled_price": fill_price,
            "filled_amount": amount,
            "amount_usd": amount_usd,
            "fee_usd": fee_usd,
            "slippage_pct": slippage * 100,
            "reason": reason,
            "timestamp": int(time.time()),
            "mode": "paper",
        }
