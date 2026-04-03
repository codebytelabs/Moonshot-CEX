"""Test v2: Try custom endpoints for stop-loss on Binance futures testnet.
The /fapi/v1/order rejects ALL conditional orders with -4120.
Try: /fapi/v2/order, /fapi/v3/order, signed raw requests.
"""
import asyncio
import hashlib
import hmac
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.exchange_ccxt import FuturesExchangeConnector
from src.config import get_settings


async def main():
    cfg = get_settings()
    fc = FuturesExchangeConnector(
        api_key=cfg.binance_demo_api_key or cfg.binance_futures_testnet_api_key,
        api_secret=cfg.binance_demo_api_secret or cfg.binance_futures_testnet_api_secret,
        name="binance",
        sandbox=True,
    )
    await fc.initialize()

    symbol = "HUMA/USDT:USDT"
    market = fc.exchange.market(symbol)
    market_id = market["id"]
    amount = fc.exchange.amount_to_precision(symbol, 114345.0)
    stop_price = fc.exchange.price_to_precision(symbol, 0.01)

    # B1: Try raw request to /fapi/v2/order
    print("\n--- B1: Raw /fapi/v2/order STOP_MARKET ---")
    try:
        resp = await fc.exchange.request("v2/order", "fapiPrivate", "POST", params={
            "symbol": market_id, "side": "SELL", "type": "STOP_MARKET",
            "quantity": str(amount), "stopPrice": str(stop_price),
            "reduceOnly": "true",
        })
        print(f"  SUCCESS: {resp}")
    except Exception as e:
        print(f"  FAIL: {e}")

    # B2: Try /fapi/v3/order
    print("\n--- B2: Raw /fapi/v3/order STOP_MARKET ---")
    try:
        resp = await fc.exchange.request("v3/order", "fapiPrivate", "POST", params={
            "symbol": market_id, "side": "SELL", "type": "STOP_MARKET",
            "quantity": str(amount), "stopPrice": str(stop_price),
            "reduceOnly": "true",
        })
        print(f"  SUCCESS: {resp}")
    except Exception as e:
        print(f"  FAIL: {e}")

    # B3: Try TAKE_PROFIT_MARKET (different conditional type)
    print("\n--- B3: TAKE_PROFIT_MARKET via /fapi/v1/order ---")
    try:
        resp = await fc.exchange.fapiPrivatePostOrder({
            "symbol": market_id, "side": "SELL", "type": "TAKE_PROFIT_MARKET",
            "quantity": str(amount), "stopPrice": str(stop_price),
            "reduceOnly": "true",
        })
        print(f"  SUCCESS: {resp}")
    except Exception as e:
        print(f"  FAIL: {e}")

    # B4: Try TRAILING_STOP_MARKET
    print("\n--- B4: TRAILING_STOP_MARKET via /fapi/v1/order ---")
    try:
        resp = await fc.exchange.fapiPrivatePostOrder({
            "symbol": market_id, "side": "SELL", "type": "TRAILING_STOP_MARKET",
            "quantity": str(amount), "callbackRate": "5",
            "reduceOnly": "true",
        })
        print(f"  SUCCESS: {resp}")
    except Exception as e:
        print(f"  FAIL: {e}")

    # B5: Check what order types the exchange says it supports
    print("\n--- B5: Supported order types for HUMAUSDT ---")
    try:
        info = market.get("info", {})
        order_types = info.get("orderTypes", [])
        print(f"  Order types: {order_types}")
        filters = info.get("filters", [])
        for f in filters:
            if "PRICE" in str(f.get("filterType", "")):
                print(f"  Filter: {f}")
    except Exception as e:
        print(f"  Error: {e}")

    # B6: Try using CCXT's editOrder / createOrderWs
    print("\n--- B6: Check available WS/edit methods ---")
    print(f"  has createStopOrder: {fc.exchange.has.get('createStopOrder')}")
    print(f"  has createStopMarketOrder: {fc.exchange.has.get('createStopMarketOrder')}")
    print(f"  has createStopLossOrder: {fc.exchange.has.get('createStopLossOrder')}")
    print(f"  has createTriggerOrder: {fc.exchange.has.get('createTriggerOrder')}")
    print(f"  has createOrderWithTakeProfitAndStopLoss: {fc.exchange.has.get('createOrderWithTakeProfitAndStopLoss')}")

    await fc.exchange.close()


if __name__ == "__main__":
    asyncio.run(main())
