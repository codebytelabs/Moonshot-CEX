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
                )
                # Also detect Binance numeric code -1013 directly
                _is_binance_notional = ("-1013" in str(e) and "notional" in err_str)
                if endpoint == "create_order" and (
                    any(p in err_str for p in _DUST_PATTERNS) or _is_binance_notional
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
