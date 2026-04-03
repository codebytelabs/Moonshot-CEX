"""Close AEVO position in chunks (max qty limit)."""
import asyncio
import sys
sys.path.insert(0, ".")

from src.exchange_ccxt import FuturesExchangeConnector
from src.config import get_settings

cfg = get_settings()


async def main():
    api_key = cfg.binance_demo_api_key or cfg.binance_futures_testnet_api_key
    api_secret = cfg.binance_demo_api_secret or cfg.binance_futures_testnet_api_secret
    fc = FuturesExchangeConnector(
        api_key=api_key, api_secret=api_secret, name="binance", sandbox=True,
    )
    await fc.initialize()

    symbol = "AEVO/USDT:USDT"
    market = fc.exchange.markets.get(symbol, {})
    max_qty = market.get("limits", {}).get("amount", {}).get("max", 10000)
    print(f"AEVO max_qty: {max_qty}")

    positions = await fc.exchange.fetch_positions([symbol])
    for pos in positions:
        contracts = abs(float(pos.get("contracts", 0)))
        if contracts <= 0:
            continue
        print(f"AEVO: {contracts} contracts to close")

        remaining = contracts
        chunk_size = 5000.0  # small chunks to avoid max qty
        while remaining > 0:
            chunk = min(remaining, chunk_size)
            amount = float(fc.exchange.amount_to_precision(symbol, chunk))
            if amount <= 0:
                break
            try:
                order = await fc.exchange.create_order(
                    symbol, "market", "sell", amount, None, {"reduceOnly": True}
                )
                print(f"  Closed {amount} ✅ order={order.get('id')}")
                remaining -= amount
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f"  Failed {amount}: {e}")
                chunk_size = chunk_size / 2
                if chunk_size < 10:
                    break

    await fc.exchange.close()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
