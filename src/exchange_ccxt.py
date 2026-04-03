"""
Async CCXT exchange connector.
Supports Gate.io (primary), Binance, and KuCoin.
Handles rate limiting, retries, market loading, and all trading operations.
"""
import asyncio
import time
from typing import Optional
from loguru import logger

import ccxt.async_support as ccxt_async

from .metrics import api_latency, errors_total


EXCHANGE_MAP = {
    "gateio": ccxt_async.gateio,
    "binance": ccxt_async.binance,
    "kucoin": ccxt_async.kucoin,
}


class ExchangeConnector:
    """Async exchange wrapper with rate limiting and retry logic."""

    def __init__(
        self,
        name: str = "gateio",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        extra: Optional[dict] = None,
        sandbox: bool = False,
        demo_url: Optional[str] = None,
    ):
        if name not in EXCHANGE_MAP:
            raise ValueError(f"Unsupported exchange: {name}. Supported: {list(EXCHANGE_MAP.keys())}")

        self.name = name
        self.demo_mode = demo_url is not None or sandbox
        opts = {
            "enableRateLimit": True,
            "timeout": 30000,
        }
        if api_key and api_secret:
            opts["apiKey"] = api_key
            opts["secret"] = api_secret
        if extra:
            opts.update(extra)

        if demo_url:
            opts["options"] = opts.get("options", {})
            opts["options"]["fetchCurrencies"] = False
            opts["options"]["fetchMargins"] = False
            opts["options"]["fetchFundingRates"] = False
            opts["options"]["defaultType"] = "spot"
            opts["options"]["fetchMarkets"] = ["spot"]

        if name == "kucoin" and extra and extra.get("password"):
            opts["password"] = extra["password"]

        self.exchange: ccxt_async.Exchange = EXCHANGE_MAP[name](opts)

        if demo_url:
            base = demo_url.rstrip("/")
            if name == "binance":
                # Map every CCXT Binance URL key to the demo base so sign()
                # never raises NotSupported for dapiPublic/eapi/papi etc.
                all_url_keys = list(self.exchange.urls.get("api", {}).keys())
                self.exchange.urls["api"] = {k: f"{base}/api/v3" for k in all_url_keys}
                self.exchange.urls["api"].update({
                    "public":        f"{base}/api/v3",
                    "private":       f"{base}/api/v3",
                    "v3":            f"{base}/api/v3",
                    "v1":            f"{base}/api/v1",
                    "sapi":          f"{base}/sapi/v1",
                    "sapiV2":        f"{base}/sapi/v2",
                    "sapiV3":        f"{base}/sapi/v3",
                    "sapiV4":        f"{base}/sapi/v4",
                    "fapiPublic":    f"{base}/fapi/v1",
                    "fapiPublicV2":  f"{base}/fapi/v2",
                    "fapiPublicV3":  f"{base}/fapi/v3",
                    "fapiPrivate":   f"{base}/fapi/v1",
                    "fapiPrivateV2": f"{base}/fapi/v2",
                    "dapiPublic":    f"{base}/dapi/v1",
                    "dapiPrivate":   f"{base}/dapi/v1",
                    "eapiPublic":    f"{base}/eapi/v1",
                    "papi":          f"{base}/papi/v1",
                })
                # Pre-populate margin pair data so parse_market() doesn't need
                # sapi/v1/margin calls (404 on demo). Without this, load_markets fails.
                self.exchange.options.setdefault("crossMarginPairsData", [])
                self.exchange.options.setdefault("isolatedMarginPairsData", [])
                self.exchange.options.setdefault("portfolioMarginSymbolsData", [])
                # Suppress the ExchangeError warning for symbol-less open-order fetches.
                self.exchange.options["warnOnFetchOpenOrdersWithoutSymbol"] = False
                # Override fetch_markets to spot-only via /api/v3/exchangeInfo.
                # CCXT Binance normally loads spot+usdm+coinm in parallel; the
                # futures endpoints return 404 on the demo URL.
                _ex_ref = self.exchange
                async def _spot_only_fetch_markets(params={}):
                    info = await _ex_ref.publicGetExchangeInfo({})
                    return _ex_ref.parse_markets(info["symbols"])
                self.exchange.fetch_markets = _spot_only_fetch_markets
            elif name == "gateio":
                if "api" in self.exchange.urls:
                    api_urls = self.exchange.urls["api"]
                    for section in list(api_urls.keys()):
                        if isinstance(api_urls[section], str):
                            api_urls[section] = base
                        elif isinstance(api_urls[section], dict):
                            for key in api_urls[section]:
                                api_urls[section][key] = base

                async def fetch_markets_spot_only(params={}):
                    return await self.exchange.fetch_spot_markets(params)
                self.exchange.fetch_markets = fetch_markets_spot_only

            logger.info(f"Exchange {name} → DEMO MODE ({base})")
        elif sandbox:
            self.exchange.set_sandbox_mode(True)
            logger.info(f"Exchange {name} → SANDBOX mode")

        self.markets_loaded = False
        self._last_request_time = 0.0

    async def initialize(self):
        """Load markets and validate connectivity."""
        try:
            t0 = time.monotonic()
            await self.exchange.load_markets()
            elapsed = time.monotonic() - t0
            self.markets_loaded = True
            n = len(self.exchange.markets)
            logger.info(f"[{self.name}] Loaded {n} markets in {elapsed:.1f}s")
            api_latency.labels(exchange=self.name, endpoint="load_markets").observe(elapsed)
        except Exception as e:
            logger.error(f"[{self.name}] Failed to load markets: {e}")
            errors_total.labels(component="exchange", error_type="load_markets").inc()
            raise

    async def close(self):
        try:
            await self.exchange.close()
        except Exception as e:
            logger.debug(f"[{self.name}] Close error: {e}")

    # ── Market Data ─────────────────────────────────────────────────────────

    async def fetch_tickers(self, symbols: Optional[list] = None) -> dict:
        return await self._retry(self.exchange.fetch_tickers, symbols, endpoint="fetch_tickers")

    async def fetch_ticker(self, symbol: str) -> dict:
        return await self._retry(self.exchange.fetch_ticker, symbol, endpoint="fetch_ticker")

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "5m", limit: int = 200, since: Optional[int] = None) -> list:
        return await self._retry(self.exchange.fetch_ohlcv, symbol, timeframe, since, limit, endpoint="fetch_ohlcv")

    async def fetch_order_book(self, symbol: str, limit: int = 20) -> dict:
        return await self._retry(self.exchange.fetch_order_book, symbol, limit, endpoint="fetch_order_book")

    # ── Account ─────────────────────────────────────────────────────────────

    async def fetch_balance(self) -> dict:
        return await self._retry(self.exchange.fetch_balance, endpoint="fetch_balance")

    async def fetch_my_trades(self, symbol: Optional[str] = None, since: Optional[int] = None, limit: Optional[int] = 50) -> list:
        return await self._retry(self.exchange.fetch_my_trades, symbol, since, limit, endpoint="fetch_my_trades")

    # ── Orders ──────────────────────────────────────────────────────────────

    async def create_market_buy(self, symbol: str, amount: float, price: Optional[float] = None) -> dict:
        logger.info(f"[{self.name}] MARKET BUY {symbol} amount={amount:.6f}")
        return await self._retry(self.exchange.create_order, symbol, "market", "buy", amount, price, endpoint="create_order")

    async def create_market_sell(self, symbol: str, amount: float) -> dict:
        logger.info(f"[{self.name}] MARKET SELL {symbol} amount={amount:.6f}")
        return await self._retry(self.exchange.create_order, symbol, "market", "sell", amount, endpoint="create_order")

    async def create_limit_buy(self, symbol: str, amount: float, price: float) -> dict:
        logger.info(f"[{self.name}] LIMIT BUY {symbol} amount={amount:.6f} price={price:.6f}")
        return await self._retry(self.exchange.create_order, symbol, "limit", "buy", amount, price, endpoint="create_order")

    async def create_limit_sell(self, symbol: str, amount: float, price: float, time_in_force: str = "gtc") -> dict:
        tif = time_in_force.upper()
        logger.info(f"[{self.name}] LIMIT SELL {symbol} amount={amount:.6f} price={price:.6f} tif={tif}")
        params = {"timeInForce": tif} if tif != "GTC" else {}
        return await self._retry(self.exchange.create_order, symbol, "limit", "sell", amount, price, params, endpoint="create_order")

    async def cancel_order(self, order_id: str, symbol: str) -> dict:
        return await self._retry(self.exchange.cancel_order, order_id, symbol, endpoint="cancel_order")

    async def fetch_order(self, order_id: str, symbol: str) -> dict:
        return await self._retry(self.exchange.fetch_order, order_id, symbol, endpoint="fetch_order")

    async def fetch_open_orders(self, symbol: Optional[str] = None) -> list:
        return await self._retry(self.exchange.fetch_open_orders, symbol, endpoint="fetch_open_orders")

    # ── Helpers ─────────────────────────────────────────────────────────────

    def get_usdt_pairs(self, min_volume_usd: float = 0) -> list:
        if not self.markets_loaded:
            return []
        return [
            symbol for symbol, market in self.exchange.markets.items()
            if market.get("quote") == "USDT"
            and market.get("active", True)
            and market.get("spot", True)
        ]

    def get_market_info(self, symbol: str) -> Optional[dict]:
        return self.exchange.markets.get(symbol)

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        try:
            return float(self.exchange.amount_to_precision(symbol, amount))
        except Exception:
            return round(amount, 6)

    def price_to_precision(self, symbol: str, price: float) -> float:
        try:
            return float(self.exchange.price_to_precision(symbol, price))
        except Exception:
            return round(price, 8)

    def cost_to_amount(self, symbol: str, cost_usd: float, price: float) -> float:
        """Convert USD cost to base asset amount, rounded to exchange precision."""
        if price <= 0:
            return 0.0
        raw_amount = cost_usd / price
        return self.amount_to_precision(symbol, raw_amount)

    # ── Retry Engine ────────────────────────────────────────────────────────

    async def _retry(self, func, *args, endpoint: str = "unknown", max_retries: int = 3):
        for attempt in range(max_retries):
            try:
                t0 = time.monotonic()
                result = await func(*args)
                elapsed = time.monotonic() - t0
                api_latency.labels(exchange=self.name, endpoint=endpoint).observe(elapsed)
                return result
            except ccxt_async.RateLimitExceeded:
                wait = 2 ** (attempt + 1)
                logger.warning(f"[{self.name}] Rate limited on {endpoint}, waiting {wait}s (attempt {attempt+1})")
                await asyncio.sleep(wait)
            except ccxt_async.NetworkError as e:
                wait = 2 ** attempt
                logger.warning(f"[{self.name}] Network error on {endpoint}: {e}, retrying in {wait}s")
                await asyncio.sleep(wait)
            except ccxt_async.ExchangeNotAvailable as e:
                wait = 5 * (attempt + 1)
                logger.error(f"[{self.name}] Exchange unavailable: {e}, retrying in {wait}s")
                await asyncio.sleep(wait)
            except ccxt_async.ExchangeError as e:
                # Binance -2013: order already filled and purged — expected for
                # instant market fills. Log at DEBUG so it doesn't pollute ERROR logs.
                if "-2013" in str(e) or "order does not exist" in str(e).lower():
                    logger.debug(f"[{self.name}] Order already filled/gone on {endpoint}: {e}")
                    raise
                err_str = str(e).lower()
                # ── Dust / sub-minimum detection ─────────────────────────────
                # Gate.io and other exchanges return ExchangeError (not retryable)
                # when the order size is below their minimum.  Detect these patterns
                # and raise SubMinimumAmountError immediately so PositionManager
                # can ghost-close the position without any further retries.
                _DUST_PATTERNS = (
                    "too small",
                    "minimum amount",
                    "minimum is",
                    "order size",
                    "less than min",
                    "below minimum",
                    "invalid_param_value",
                    "filter failure: notional",   # Binance -1013: notional < $5
                    "filter failure: lot_size",   # Binance -1013: qty below min lot
                    "filter failure: min_notional",
                    # NOTE: "quantity greater than max" (-4005) is NOT a dust error —
                    # it means the order is TOO LARGE. Handled by _clamp_amount and
                    # entry retry loop in FuturesExecutionCore.
                    "no smaller than",             # Binance futures -4164 min notional
                )
                # Also detect Binance numeric code -1013 directly
                _is_binance_notional = ("-1013" in str(e) and "notional" in err_str)
                _is_binance_futures_qty = ("-4164" in str(e))  # -4005 is max qty, not min
                if endpoint == "create_order" and (
                    any(p in err_str for p in _DUST_PATTERNS) or _is_binance_notional or _is_binance_futures_qty
                ):
                    from .execution_core import SubMinimumAmountError  # late import avoids circular
                    # Extract symbol from args[0] if available
                    sym = str(args[0]) if args else "unknown"
                    logger.warning(
                        f"[{self.name}] Dust/sub-minimum order rejected for {sym}: {e}"
                    )
                    raise SubMinimumAmountError(
                        symbol=sym,
                        amount=float(args[3]) if len(args) > 3 else 0.0,
                        min_amount=0.0,
                        price=float(args[4]) if len(args) > 4 else 0.0,
                        reason="exchange_min_size",
                    )
                # ─────────────────────────────────────────────────────────────
                # "does not have market symbol" on fetch_ohlcv is expected on
                # testnet (limited symbol set) — downgrade to DEBUG.
                if endpoint == "fetch_ohlcv" and "does not have market symbol" in str(e):
                    logger.debug(f"[{self.name}] Symbol not on exchange for {endpoint}: {e}")
                else:
                    logger.error(f"[{self.name}] Exchange error on {endpoint}: {e}")
                errors_total.labels(component="exchange", error_type="exchange_error").inc()
                raise
            except Exception as e:
                # fetch_my_trades on Binance demo returns malformed responses (NoneType).
                # This is non-critical — downgrade to DEBUG so it doesn't pollute ERROR logs.
                if endpoint == "fetch_my_trades":
                    logger.debug(f"[{self.name}] fetch_my_trades parse error (non-critical): {e}")
                else:
                    logger.error(f"[{self.name}] Unexpected error on {endpoint}: {e}")
                errors_total.labels(component="exchange", error_type="unexpected").inc()
                raise


        errors_total.labels(component="exchange", error_type="max_retries").inc()
        raise Exception(f"Max retries ({max_retries}) exhausted for {self.name}.{endpoint}")


class FuturesExchangeConnector(ExchangeConnector):
    """Extends ExchangeConnector for Binance USDM Futures (Testnet or live).

    Key differences from spot:
      - defaultType = "future" (linear USDT-margined perps)
      - set_leverage() / set_margin_type() per symbol
      - Futures-aware balance fetch (wallet + unrealized PnL)
      - Funding rate queries
      - Position info queries
    """

    def __init__(
        self,
        name: str = "binance",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        futures_url: Optional[str] = None,
        default_leverage: int = 3,
        margin_type: str = "isolated",
        sandbox: bool = False,
    ):
        if name not in EXCHANGE_MAP:
            raise ValueError(f"Unsupported exchange: {name}")

        self.name = name
        self.demo_mode = futures_url is not None or sandbox
        self._default_leverage = default_leverage
        self._margin_type = margin_type.upper()  # ISOLATED or CROSSED
        self._leverage_cache: dict[str, int] = {}  # symbol → leverage set

        opts = {
            "enableRateLimit": True,
            "timeout": 30000,
            "options": {
                "defaultType": "future",
                "fetchCurrencies": False,
                "fetchMargins": False,
                "adjustForTimeDifference": True,
            },
        }
        if api_key and api_secret:
            opts["apiKey"] = api_key
            opts["secret"] = api_secret

        self.exchange: ccxt_async.Exchange = EXCHANGE_MAP[name](opts)

        # Use CCXT's native sandbox mode — it correctly maps every endpoint
        # type (fapi, sapi, public, private, dapi, etc.) to proper testnet URLs.
        # Manual URL overrides break endpoints that use different path prefixes.
        if futures_url or sandbox:
            if name == "binance":
                self.exchange.set_sandbox_mode(True)
                self.exchange.options.setdefault("crossMarginPairsData", [])
                self.exchange.options.setdefault("isolatedMarginPairsData", [])
                self.exchange.options.setdefault("portfolioMarginSymbolsData", [])
                self.exchange.options["warnOnFetchOpenOrdersWithoutSymbol"] = False

            logger.info(f"FuturesExchange {name} → FUTURES SANDBOX (testnet)")

        self.markets_loaded = False
        self._last_request_time = 0.0

    # ── Futures-specific: Leverage & Margin ────────────────────────────────

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a symbol. Returns True on success."""
        if self._leverage_cache.get(symbol) == leverage:
            logger.debug(f"[Futures] Leverage {symbol} already {leverage}x (cached), skipping")
            return True
        try:
            await self._retry(
                self.exchange.set_leverage, leverage, symbol,
                endpoint="set_leverage",
            )
            self._leverage_cache[symbol] = leverage
            logger.info(f"[Futures] Set leverage {symbol} → {leverage}x")
            return True
        except Exception as e:
            # Some symbols may not support the requested leverage
            logger.warning(f"[Futures] Failed to set leverage {symbol} {leverage}x: {e}")
            return False

    async def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> bool:
        """Set margin type (ISOLATED or CROSSED) for a symbol."""
        try:
            await self._retry(
                self.exchange.set_margin_mode,
                margin_type.lower(), symbol,
                endpoint="set_margin_mode",
            )
            logger.info(f"[Futures] Set margin {symbol} → {margin_type}")
            return True
        except ccxt_async.ExchangeError as e:
            # "No need to change margin type" is OK — already set
            if "no need to change" in str(e).lower() or "already" in str(e).lower():
                logger.debug(f"[Futures] Margin already {margin_type} for {symbol}")
                return True
            logger.warning(f"[Futures] Failed to set margin {symbol}: {e}")
            return False

    async def prepare_symbol(self, symbol: str, leverage: int) -> bool:
        """Set both margin type and leverage for a symbol before trading."""
        margin_ok = await self.set_margin_type(symbol, self._margin_type)
        lev_ok = await self.set_leverage(symbol, leverage)
        return margin_ok and lev_ok

    # ── Futures-specific: Positions & Funding ──────────────────────────────

    async def fetch_positions(self, symbols: Optional[list[str]] = None) -> list[dict]:
        """Fetch open futures positions."""
        try:
            return await self._retry(
                self.exchange.fetch_positions, symbols,
                endpoint="fetch_positions",
            )
        except Exception as e:
            logger.warning(f"[Futures] fetch_positions error: {e}")
            return []

    async def fetch_funding_rate(self, symbol: str) -> float:
        """Fetch current funding rate for a perpetual contract."""
        try:
            result = await self._retry(
                self.exchange.fetch_funding_rate, symbol,
                endpoint="fetch_funding_rate",
            )
            return float(result.get("fundingRate", 0.0))
        except Exception as e:
            logger.debug(f"[Futures] fetch_funding_rate error for {symbol}: {e}")
            return 0.0

    async def fetch_funding_rates(self, symbols: Optional[list[str]] = None) -> dict[str, float]:
        """Fetch funding rates for multiple symbols."""
        rates = {}
        try:
            result = await self._retry(
                self.exchange.fetch_funding_rates, symbols,
                endpoint="fetch_funding_rates",
            )
            for sym, data in result.items():
                rates[sym] = float(data.get("fundingRate", 0.0))
        except Exception as e:
            logger.debug(f"[Futures] fetch_funding_rates error: {e}")
        return rates

    async def fetch_futures_balance(self) -> dict:
        """Fetch futures wallet balance (available margin + unrealized PnL)."""
        try:
            bal = await self._retry(self.exchange.fetch_balance, endpoint="fetch_balance")
            usdt = bal.get("USDT", {})
            return {
                "total": float(usdt.get("total", 0.0)),
                "free": float(usdt.get("free", 0.0)),
                "used": float(usdt.get("used", 0.0)),
            }
        except Exception as e:
            logger.warning(f"[Futures] fetch_futures_balance error: {e}")
            return {"total": 0.0, "free": 0.0, "used": 0.0}

    # ── Futures Orders ─────────────────────────────────────────────────────

    def _clamp_amount(self, symbol: str, amount: float) -> float:
        """Clamp order amount to exchange max quantity limit for the symbol.

        CCXT doesn't always parse maxQty into limits.amount.max for Binance
        futures markets.  Fall back to reading the raw MARKET_LOT_SIZE /
        LOT_SIZE filters from market['info']['filters'].
        """
        market = self.exchange.markets.get(symbol)
        if market:
            max_qty = market.get("limits", {}).get("amount", {}).get("max")
            # Fallback: read raw Binance filters if CCXT didn't parse max
            if not max_qty:
                for f in (market.get("info", {}).get("filters") or []):
                    if f.get("filterType") in ("MARKET_LOT_SIZE", "LOT_SIZE"):
                        _mq = float(f.get("maxQty", 0))
                        if _mq > 0:
                            max_qty = _mq
                            break
            if max_qty and amount > max_qty:
                logger.warning(f"[Futures] {symbol} amount {amount:.2f} exceeds max {max_qty:.2f}, clamping")
                amount = float(max_qty) * 0.99  # 1% below max for safety
        return self.exchange.amount_to_precision(symbol, amount)

    async def open_long(self, symbol: str, amount: float, leverage: int = 0) -> dict:
        """Open a long futures position (market buy)."""
        if leverage > 0:
            await self.prepare_symbol(symbol, leverage)
        amount = float(self._clamp_amount(symbol, amount))
        logger.info(f"[Futures] OPEN LONG {symbol} amount={amount:.6f} lev={leverage}x")
        return await self._retry(
            self.exchange.create_order, symbol, "market", "buy", amount,
            endpoint="create_order",
        )

    async def close_long(self, symbol: str, amount: float) -> dict:
        """Close a long futures position (market sell with reduceOnly)."""
        logger.info(f"[Futures] CLOSE LONG {symbol} amount={amount:.6f}")
        return await self._retry(
            self.exchange.create_order, symbol, "market", "sell", amount,
            None, {"reduceOnly": True},
            endpoint="create_order",
        )

    async def open_short(self, symbol: str, amount: float, leverage: int = 0) -> dict:
        """Open a short futures position (market sell)."""
        if leverage > 0:
            await self.prepare_symbol(symbol, leverage)
        amount = float(self._clamp_amount(symbol, amount))
        logger.info(f"[Futures] OPEN SHORT {symbol} amount={amount:.6f} lev={leverage}x")
        return await self._retry(
            self.exchange.create_order, symbol, "market", "sell", amount,
            endpoint="create_order",
        )

    async def close_short(self, symbol: str, amount: float) -> dict:
        """Close a short futures position (market buy with reduceOnly)."""
        logger.info(f"[Futures] CLOSE SHORT {symbol} amount={amount:.6f}")
        return await self._retry(
            self.exchange.create_order, symbol, "market", "buy", amount,
            None, {"reduceOnly": True},
            endpoint="create_order",
        )

    # ── Exchange-side stop-loss orders ─────────────────────────────────────
    # Binance breaking change (2025-12-09): ALL conditional orders (STOP_MARKET,
    # TAKE_PROFIT_MARKET, etc.) moved from /fapi/v1/order to /fapi/v1/algoOrder.
    # CCXT doesn't map this endpoint, so we use exchange.request() directly.
    # Docs: https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order

    async def place_stop_loss_order(
        self, symbol: str, side: str, amount: float, stop_price: float
    ) -> Optional[dict]:
        """Place a STOP_MARKET algo order on Binance as a safety net.

        Args:
            symbol: e.g. "BTC/USDT:USDT"
            side: "long" or "short" — the POSITION side (order side is inverse)
            amount: position size in base units
            stop_price: trigger price for the stop
        Returns:
            Dict with 'id' (algoId) or None on failure.
        """
        try:
            amount = float(self._clamp_amount(symbol, amount))
            stop_price = float(self.exchange.price_to_precision(symbol, stop_price))
            if amount <= 0 or stop_price <= 0:
                return None

            market = self.exchange.market(symbol)
            market_id = market["id"]
            order_side = "SELL" if side == "long" else "BUY"

            resp = await self.exchange.request("algoOrder", "fapiPrivate", "POST", params={
                "symbol": market_id,
                "side": order_side,
                "type": "STOP_MARKET",
                "algoType": "CONDITIONAL",
                "quantity": str(self.exchange.amount_to_precision(symbol, amount)),
                "triggerPrice": str(stop_price),
                "reduceOnly": "true",
                "workingType": "CONTRACT_PRICE",
            })
            algo_id = str(resp.get("algoId", ""))
            logger.info(
                f"[Futures] SL ORDER placed: {symbol} {order_side} {amount} "
                f"@ stop={stop_price} → algoId={algo_id}"
            )
            return {"id": algo_id, "algoId": algo_id, "status": resp.get("algoStatus")}
        except Exception as e:
            logger.warning(f"[Futures] Failed to place SL order for {symbol}: {e}")
            return None

    async def cancel_stop_loss_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an exchange-side algo stop-loss order. Returns True on success."""
        if not order_id:
            return False
        try:
            await self.exchange.request("algoOrder", "fapiPrivate", "DELETE", params={
                "algoId": str(order_id),
            })
            logger.info(f"[Futures] SL ORDER cancelled: {symbol} algoId={order_id}")
            return True
        except Exception as e:
            logger.debug(f"[Futures] Could not cancel SL order {order_id} for {symbol}: {e}")
            return False

    async def update_stop_loss_order(
        self, symbol: str, old_order_id: str, side: str, amount: float, new_stop_price: float
    ) -> Optional[dict]:
        """Cancel old SL and place new one at updated price (e.g. trailing tightened)."""
        await self.cancel_stop_loss_order(symbol, old_order_id)
        return await self.place_stop_loss_order(symbol, side, amount, new_stop_price)

    # ── Override get_usdt_pairs for futures ────────────────────────────────

    def get_usdt_pairs(self, min_volume_usd: float = 0) -> list:
        """Return USDT-margined linear perpetual pairs."""
        if not self.markets_loaded:
            return []
        return [
            symbol for symbol, market in self.exchange.markets.items()
            if market.get("quote") == "USDT"
            and market.get("active", True)
            and market.get("linear", False)
            and market.get("swap", False)
        ]
