"""
Dust Cleaner — sweeps all exchange holdings below DUST_THRESHOLD USD.

How it works:
  1. Fetch all non-zero balances from the exchange.
  2. For each non-stablecoin asset:
       • If 0 < value < MIN_NOTIONAL ($10.5):  buy just enough to reach MIN_NOTIONAL, then sell all.
       • If MIN_NOTIONAL <= value < DUST_THRESHOLD ($50): sell all directly at market.
       • If value >= DUST_THRESHOLD: skip (not dust).
  3. Default mode is DRY RUN — prints what WOULD happen, touches nothing.
     Pass --execute to actually fire the orders.

Usage:
  python scripts/dust_cleaner.py                        # dry-run (safe)
  python scripts/dust_cleaner.py --execute              # live orders
  python scripts/dust_cleaner.py --dust-threshold 100   # treat < $100 as dust
  python scripts/dust_cleaner.py --min-notional 12      # use $12 as minimum
"""

import asyncio
import argparse
import math
import sys
import os

# Allow running from repo root or scripts/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from loguru import logger
from src.config import get_settings
from src.exchange_ccxt import ExchangeConnector


def _topup_qty_ceil(exchange: "ExchangeConnector", symbol: str, topup_usd: float, price: float) -> float:
    """Compute top-up quantity using ceiling rounding so the buy notional always
    meets the exchange minimum after precision truncation."""
    raw_qty = topup_usd / price
    try:
        market = exchange.exchange.markets.get(symbol, {})
        precision = (market.get("precision") or {}).get("amount")
        if precision is not None:
            step = 10 ** (-int(precision)) if isinstance(precision, int) else float(precision)
            qty = math.ceil(raw_qty / step) * step
            dp = max(0, round(-math.log10(step))) if step < 1 else 0
            return round(qty, dp)
    except Exception:
        pass
    return exchange.cost_to_amount(symbol, topup_usd, price)


# Stablecoins and wrapped assets that should never be sold as "dust"
_SKIP_ASSETS = frozenset({
    "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI", "USDP",
    "GUSD", "USDX", "USDD", "USDJ", "LUSD", "FRAX",
    "SUSD", "MUSD", "STBT", "USDE", "PYUSD",
    "WBTC", "WETH", "WBNB",
})


def _build_exchange(cfg) -> ExchangeConnector:
    name = cfg.exchange_name
    mode = cfg.exchange_mode

    if name == "gateio":
        if mode == "demo":
            return ExchangeConnector(
                name="gateio",
                api_key=cfg.gateio_testnet_api_key,
                api_secret=cfg.gateio_testnet_secret_key,
                demo_url=cfg.gateio_testnet_url,
            )
        else:
            return ExchangeConnector(
                name="gateio",
                api_key=cfg.gateio_api_key if mode == "live" else None,
                api_secret=cfg.gateio_api_secret if mode == "live" else None,
            )
    elif name == "binance":
        if mode == "demo":
            return ExchangeConnector(
                name="binance",
                api_key=cfg.binance_demo_api_key,
                api_secret=cfg.binance_demo_api_secret,
                demo_url=cfg.binance_demo_url,
            )
        else:
            return ExchangeConnector(
                name="binance",
                api_key=cfg.binance_api_key if mode == "live" else None,
                api_secret=cfg.binance_api_secret if mode == "live" else None,
            )
    elif name == "kucoin":
        extra = {}
        if cfg.kucoin_passphrase:
            extra["password"] = cfg.kucoin_passphrase
        return ExchangeConnector(
            name="kucoin",
            api_key=cfg.kucoin_api_key if mode == "live" else None,
            api_secret=cfg.kucoin_api_secret if mode == "live" else None,
            extra=extra if extra else None,
        )
    else:
        raise ValueError(f"Unsupported exchange: {name}")


async def run(dust_threshold: float, min_notional: float, min_value: float, execute: bool) -> None:
    cfg = get_settings()
    exchange = _build_exchange(cfg)

    mode_label = f"{cfg.exchange_name.upper()} [{cfg.exchange_mode}]"
    dry = not execute

    logger.info("=" * 60)
    logger.info(f"  DUST CLEANER — {mode_label}")
    logger.info(f"  Dust threshold : < ${dust_threshold:.2f}")
    logger.info(f"  Min value      : >= ${min_value:.2f} (skip below this)")
    logger.info(f"  Min notional   : ${min_notional:.2f}")
    logger.info(f"  Mode           : {'DRY RUN (pass --execute to trade)' if dry else '⚡ LIVE — WILL PLACE REAL ORDERS'}")
    logger.info("=" * 60)

    try:
        await exchange.initialize()
    except Exception as e:
        logger.error(f"Failed to load markets: {e}")
        await exchange.close()
        return

    # Fetch all balances
    try:
        balance = await exchange.fetch_balance()
    except Exception as e:
        logger.error(f"Failed to fetch balance: {e}")
        await exchange.close()
        return

    dust_items = []
    skipped = []

    for asset, data in balance.items():
        if asset in ("info", "free", "used", "total", "timestamp", "datetime"):
            continue
        if not isinstance(data, dict):
            continue

        free = float(data.get("free") or 0.0)
        if free <= 0:
            continue

        if asset in _SKIP_ASSETS:
            skipped.append((asset, free, "stablecoin/skip"))
            continue

        symbol = f"{asset}/USDT"
        # Check market exists
        if symbol not in exchange.exchange.markets:  # markets dict is on inner exchange
            skipped.append((asset, free, "no USDT pair"))
            continue

        try:
            ticker = await exchange.fetch_ticker(symbol)
            price = float(ticker.get("last") or 0.0)
        except Exception:
            skipped.append((asset, free, "price fetch failed"))
            continue

        if price <= 0:
            skipped.append((asset, free, "zero price"))
            continue

        usd_value = free * price

        if usd_value <= 0:
            skipped.append((asset, free, "zero value"))
            continue

        if usd_value < min_value:
            skipped.append((asset, free, f"${usd_value:.4f} < min_value=${min_value:.2f}, skip (not worth top-up cost)"))
            continue

        if usd_value >= dust_threshold:
            skipped.append((asset, free, f"${usd_value:.2f} >= threshold, not dust"))
            continue

        dust_items.append({
            "asset":     asset,
            "symbol":    symbol,
            "free":      free,
            "price":     price,
            "usd_value": usd_value,
            "needs_topup": usd_value < min_notional,
        })

    if not dust_items:
        logger.info("No dust found! Exchange is already clean.")
        await exchange.close()
        return

    logger.info(f"\nFound {len(dust_items)} dust position(s):\n")
    total_recovered = 0.0
    topup_cost = 0.0

    for item in dust_items:
        asset      = item["asset"]
        symbol     = item["symbol"]
        free       = item["free"]
        price      = item["price"]
        usd_value  = item["usd_value"]
        needs_topup = item["needs_topup"]

        if needs_topup:
            # How much USD to buy to bring it to min_notional
            topup_usd = min_notional - usd_value + 0.10  # +$0.10 buffer for precision
            topup_qty = _topup_qty_ceil(exchange, symbol, topup_usd, price)
            sell_qty  = exchange.amount_to_precision(symbol, free + topup_qty)
            topup_cost += topup_usd

            logger.info(
                f"  {asset:10s} ${usd_value:7.2f}  → TOP-UP ${topup_usd:.2f} "
                f"(buy {topup_qty:.6f} @ ${price:.4f}) → sell {sell_qty:.6f} all"
            )
        else:
            sell_qty = exchange.amount_to_precision(symbol, free)
            logger.info(
                f"  {asset:10s} ${usd_value:7.2f}  → SELL {sell_qty:.6f} @ ${price:.4f}"
            )

        total_recovered += usd_value
        item["sell_qty"] = sell_qty
        item["topup_qty"] = topup_qty if needs_topup else 0.0

    logger.info(f"\nSummary: ~${total_recovered:.2f} to recover | ~${topup_cost:.2f} top-up cost")

    if dry:
        logger.info("\n[DRY RUN] No orders placed. Re-run with --execute to sweep dust.")
        await exchange.close()
        return

    # ── Execute ──────────────────────────────────────────────────────────────
    logger.info("\n⚡ Executing dust sweep...\n")
    swept = 0
    errors = 0

    for item in dust_items:
        asset    = item["asset"]
        symbol   = item["symbol"]
        sell_qty = item["sell_qty"]
        topup_qty = item["topup_qty"]
        price    = item["price"]

        try:
            # Step 1: re-fetch live balance to get accurate pre-buy qty and decide top-up
            try:
                pre = await exchange.fetch_balance()
                live_free = float((pre.get(asset) or {}).get("free") or 0.0)
                live_usd  = live_free * price
            except Exception:
                live_free = item["free"]
                live_usd  = item["usd_value"]

            # Recompute remaining top-up gap from live balance
            remaining_gap = max(0.0, min_notional - live_usd)

            if item["needs_topup"] and remaining_gap >= 2.0:
                # Gap is large enough to place a valid buy order
                actual_topup_usd = remaining_gap + 0.10
                actual_topup_qty = _topup_qty_ceil(exchange, symbol, actual_topup_usd, price)
                logger.info(f"  [{asset}] Buying {actual_topup_qty:.6f} to meet min notional (gap=${remaining_gap:.2f})...")
                await exchange.create_market_buy(symbol, actual_topup_qty, price)
                await asyncio.sleep(1.5)  # wait for order to settle into free balance
            elif item["needs_topup"] and remaining_gap < 2.0:
                logger.info(f"  [{asset}] Gap=${remaining_gap:.2f} too small to buy, selling existing balance directly...")

            # Step 2: re-fetch actual free balance after any buy
            try:
                fresh = await exchange.fetch_balance()
                actual_free = float((fresh.get(asset) or {}).get("free") or 0.0)
                if actual_free > 0:
                    sell_qty = exchange.amount_to_precision(symbol, actual_free)
                else:
                    logger.warning(f"  [{asset}] Zero free balance, skipping")
                    continue
            except Exception as fe:
                logger.warning(f"  [{asset}] Balance fetch failed ({fe}), using pre-computed qty")

            # Step 3: sell all
            logger.info(f"  [{asset}] Selling {sell_qty:.6f} at market...")
            await exchange.create_market_sell(symbol, sell_qty)
            logger.info(f"  [{asset}] ✓ Swept ~${item['usd_value']:.2f}")
            swept += 1
            await asyncio.sleep(0.3)

        except Exception as e:
            logger.error(f"  [{asset}] ✗ Failed: {e}")
            errors += 1

    logger.info(f"\n{'=' * 60}")
    logger.info(f"  Dust sweep complete: {swept} swept, {errors} errors")
    logger.info(f"{'=' * 60}")

    await exchange.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep dust holdings from exchange account")
    parser.add_argument(
        "--dust-threshold",
        type=float,
        default=50.0,
        help="Max USD value to treat as dust (default: $50)",
    )
    parser.add_argument(
        "--min-notional",
        type=float,
        default=10.5,
        help="Minimum order notional — buy up to this before selling (default: $10.5)",
    )
    parser.add_argument(
        "--min-value",
        type=float,
        default=1.0,
        help="Minimum current USD value to process (default: $1.00). Positions below this are skipped — topping up a $0.01 position costs $10.59 in buys and only recovers $0.01.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually place orders. Without this flag, runs as dry-run.",
    )
    args = parser.parse_args()

    asyncio.run(run(
        dust_threshold=args.dust_threshold,
        min_notional=args.min_notional,
        min_value=args.min_value,
        execute=args.execute,
    ))


if __name__ == "__main__":
    main()
