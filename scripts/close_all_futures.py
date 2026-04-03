"""Emergency: close ALL open futures positions on testnet."""
import asyncio
import sys
sys.path.insert(0, ".")

from src.exchange_ccxt import FuturesExchangeConnector
from src.config import get_settings

cfg = get_settings()


async def main():
    print("=== EMERGENCY: Close all futures positions ===")
    # Use demo keys (same keys work for futures testnet)
    api_key = cfg.binance_demo_api_key or cfg.binance_futures_testnet_api_key
    api_secret = cfg.binance_demo_api_secret or cfg.binance_futures_testnet_api_secret
    fc = FuturesExchangeConnector(
        api_key=api_key,
        api_secret=api_secret,
        name="binance",
        sandbox=True,
    )
    await fc.initialize()
    print(f"Connected. Markets loaded: {fc.markets_loaded}")

    positions = await fc.exchange.fetch_positions()
    open_positions = [p for p in positions if abs(float(p.get("contracts", 0))) > 0]
    print(f"Found {len(open_positions)} open positions")

    for pos in open_positions:
        symbol = pos["symbol"]
        contracts = abs(float(pos["contracts"]))
        side = pos.get("side", "long")
        notional = float(pos.get("notional", 0) or 0)
        pnl = float(pos.get("unrealizedPnl", 0) or 0)
        print(f"  {symbol}: {side} {contracts} contracts, notional=${abs(notional):.2f}, PnL=${pnl:.2f}")

        try:
            amount = fc.exchange.amount_to_precision(symbol, contracts)
            if side == "long":
                order = await fc.exchange.create_order(
                    symbol, "market", "sell", float(amount),
                    None, {"reduceOnly": True}
                )
            else:
                order = await fc.exchange.create_order(
                    symbol, "market", "buy", float(amount),
                    None, {"reduceOnly": True}
                )
            print(f"    CLOSED ✅ order={order.get('id')}")
        except Exception as e:
            print(f"    FAILED ❌ {e}")

    await fc.exchange.close()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
