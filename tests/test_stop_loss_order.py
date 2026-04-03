"""Test script to find the correct way to place STOP_MARKET / STOP orders
on Binance USDM Futures testnet via CCXT 4.x.

Error -4120: "Order type not supported for this endpoint. Please use the Algo Order API endpoints instead."

We test multiple approaches:
A1: STOP (stop-limit) via fapiPrivatePostOrder — most basic conditional order
A2: STOP_MARKET with workingType=MARK_PRICE
A3: STOP_MARKET with closePosition=true
A4: Raw request to /fapi/v1/order with different params
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.exchange_ccxt import FuturesExchangeConnector
from src.config import get_settings


async def get_connector():
    cfg = get_settings()
    fc = FuturesExchangeConnector(
        api_key=cfg.binance_demo_api_key or cfg.binance_futures_testnet_api_key,
        api_secret=cfg.binance_demo_api_secret or cfg.binance_futures_testnet_api_secret,
        name="binance",
        sandbox=True,
    )
    await fc.initialize()
    return fc


async def test_a1_stop_limit(fc, symbol, side, amount, stop_price):
    """A1: STOP (stop-limit) order — limit price set aggressively near trigger."""
    print("\n--- A1: STOP (stop-limit) via create_order ---")
    # For a SELL stop (long SL): limit slightly below stop to ensure fill
    # For a BUY stop (short SL): limit slightly above stop
    if side == "sell":
        limit_price = float(fc.exchange.price_to_precision(symbol, stop_price * 0.90))
    else:
        limit_price = float(fc.exchange.price_to_precision(symbol, stop_price * 1.10))
    try:
        order = await fc.exchange.create_order(
            symbol, "STOP", side, amount, limit_price,
            {"stopPrice": stop_price, "reduceOnly": True, "timeInForce": "GTC"},
        )
        print(f"  SUCCESS: id={order.get('id')} type={order.get('type')} status={order.get('status')}")
        return order
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return None


async def test_a2_stop_market_workingtype(fc, symbol, side, amount, stop_price):
    """A2: STOP_MARKET with workingType=MARK_PRICE."""
    print("\n--- A2: STOP_MARKET + workingType=MARK_PRICE ---")
    try:
        order = await fc.exchange.create_order(
            symbol, "STOP_MARKET", side, amount, None,
            {"stopPrice": stop_price, "reduceOnly": True, "workingType": "MARK_PRICE"},
        )
        print(f"  SUCCESS: id={order.get('id')} type={order.get('type')}")
        return order
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return None


async def test_a3_stop_market_closeposition(fc, symbol, side, stop_price):
    """A3: STOP_MARKET with closePosition=true (no amount needed)."""
    print("\n--- A3: STOP_MARKET + closePosition=true ---")
    try:
        order = await fc.exchange.create_order(
            symbol, "STOP_MARKET", side, None, None,
            {"stopPrice": stop_price, "closePosition": True},
        )
        print(f"  SUCCESS: id={order.get('id')} type={order.get('type')}")
        return order
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return None


async def test_a4_raw_stop(fc, symbol, side, amount, stop_price):
    """A4: Raw fapiPrivatePostOrder with STOP type."""
    print("\n--- A4: Raw fapiPrivatePostOrder STOP ---")
    market = fc.exchange.market(symbol)
    market_id = market["id"]  # e.g. "HUMAUSDT"
    limit_price = stop_price * 0.90 if side == "sell" else stop_price * 1.10
    try:
        resp = await fc.exchange.fapiPrivatePostOrder({
            "symbol": market_id,
            "side": side.upper(),
            "type": "STOP",
            "quantity": str(fc.exchange.amount_to_precision(symbol, amount)),
            "price": str(fc.exchange.price_to_precision(symbol, limit_price)),
            "stopPrice": str(fc.exchange.price_to_precision(symbol, stop_price)),
            "reduceOnly": "true",
            "timeInForce": "GTC",
        })
        print(f"  SUCCESS: orderId={resp.get('orderId')} type={resp.get('type')} status={resp.get('status')}")
        return resp
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return None


async def test_a5_raw_stop_market(fc, symbol, side, amount, stop_price):
    """A5: Raw fapiPrivatePostOrder with STOP_MARKET type."""
    print("\n--- A5: Raw fapiPrivatePostOrder STOP_MARKET ---")
    market = fc.exchange.market(symbol)
    market_id = market["id"]
    try:
        resp = await fc.exchange.fapiPrivatePostOrder({
            "symbol": market_id,
            "side": side.upper(),
            "type": "STOP_MARKET",
            "quantity": str(fc.exchange.amount_to_precision(symbol, amount)),
            "stopPrice": str(fc.exchange.price_to_precision(symbol, stop_price)),
            "reduceOnly": "true",
            "workingType": "MARK_PRICE",
        })
        print(f"  SUCCESS: orderId={resp.get('orderId')} type={resp.get('type')}")
        return resp
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return None


async def cancel_order(fc, symbol, order):
    """Cancel an order by its ID."""
    oid = order.get("id") or order.get("orderId")
    if oid:
        try:
            await fc.exchange.cancel_order(str(oid), symbol)
            print(f"  Cancelled order {oid} ✅")
        except Exception as e:
            print(f"  Cancel failed for {oid}: {e}")


async def main():
    fc = await get_connector()

    # Use HUMA which has an open long position
    symbol = "HUMA/USDT:USDT"
    side = "sell"  # SL for long = sell
    amount = 114345.0
    stop_price = 0.01  # well below current price

    results = {}

    # Test each approach
    for label, test_fn in [
        ("A1_stop_limit", lambda: test_a1_stop_limit(fc, symbol, side, amount, stop_price)),
        ("A2_stop_market_wt", lambda: test_a2_stop_market_workingtype(fc, symbol, side, amount, stop_price)),
        ("A3_stop_market_cp", lambda: test_a3_stop_market_closeposition(fc, symbol, side, stop_price)),
        ("A4_raw_stop", lambda: test_a4_raw_stop(fc, symbol, side, amount, stop_price)),
        ("A5_raw_stop_market", lambda: test_a5_raw_stop_market(fc, symbol, side, amount, stop_price)),
    ]:
        order = await test_fn()
        results[label] = order is not None
        if order:
            await cancel_order(fc, symbol, order)

    print("\n" + "=" * 50)
    print("RESULTS SUMMARY:")
    for label, ok in results.items():
        print(f"  {label}: {'✅ WORKS' if ok else '❌ FAILED'}")

    await fc.exchange.close()


if __name__ == "__main__":
    asyncio.run(main())
