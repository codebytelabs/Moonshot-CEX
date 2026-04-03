"""Integration test: FuturesExchangeConnector.place/cancel/update_stop_loss_order
using Binance's /fapi/v1/algoOrder endpoint (breaking change Dec 2025).
"""
import asyncio
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
    amount = 114345.0
    stop_price = 0.01
    passed = 0
    total = 4

    # ── TEST 1: place_stop_loss_order ──
    print("--- TEST 1: place_stop_loss_order (long SL) ---")
    order = await fc.place_stop_loss_order(symbol, "long", amount, stop_price)
    if order and order.get("id"):
        print(f"  ✅ PASS — algoId={order['id']} status={order.get('status')}")
        passed += 1
    else:
        print(f"  ❌ FAIL — returned {order}")

    # ── TEST 2: Verify it appears in open algo orders ──
    print("\n--- TEST 2: Verify order in open algo orders ---")
    try:
        open_orders = await fc.exchange.request("openAlgoOrders", "fapiPrivate", "GET", params={})
        found = any(str(o.get("algoId")) == str(order["id"]) for o in open_orders) if order else False
        if found:
            print(f"  ✅ PASS — found algoId={order['id']} in {len(open_orders)} open orders")
            passed += 1
        else:
            print(f"  ❌ FAIL — not found. Open orders: {open_orders}")
    except Exception as e:
        print(f"  ❌ FAIL — {e}")

    # ── TEST 3: cancel_stop_loss_order ──
    print("\n--- TEST 3: cancel_stop_loss_order ---")
    if order:
        ok = await fc.cancel_stop_loss_order(symbol, order["id"])
        if ok:
            print(f"  ✅ PASS — cancelled algoId={order['id']}")
            passed += 1
        else:
            print(f"  ❌ FAIL — cancel returned False")
    else:
        print("  ⏭ SKIPPED (no order to cancel)")

    # ── TEST 4: update_stop_loss_order (place → cancel old → place new) ──
    print("\n--- TEST 4: update_stop_loss_order ---")
    order1 = await fc.place_stop_loss_order(symbol, "long", amount, 0.009)
    if order1:
        order2 = await fc.update_stop_loss_order(symbol, order1["id"], "long", amount, 0.008)
        if order2 and order2.get("id") and order2["id"] != order1["id"]:
            print(f"  ✅ PASS — old={order1['id']} → new={order2['id']}")
            passed += 1
            await fc.cancel_stop_loss_order(symbol, order2["id"])
        else:
            print(f"  ❌ FAIL — update returned {order2}")
            if order1:
                await fc.cancel_stop_loss_order(symbol, order1["id"])
    else:
        print("  ❌ FAIL — initial placement failed")

    print(f"\n{'='*50}")
    print(f"RESULTS: {passed}/{total} tests passed {'✅' if passed == total else '❌'}")

    await fc.exchange.close()


if __name__ == "__main__":
    asyncio.run(main())
