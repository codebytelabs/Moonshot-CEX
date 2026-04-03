"""
Test the full futures startup path from server.py without MongoDB/Redis.
Verifies: exchange init, wiring, equity fetch, symbol loading, strategy scanning.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

PASS_COUNT = 0
FAIL_COUNT = 0


def ok(msg):
    global PASS_COUNT
    PASS_COUNT += 1
    print(f"  [PASS] {msg}")


def fail(msg):
    global FAIL_COUNT
    FAIL_COUNT += 1
    print(f"  [FAIL] {msg}")


async def main():
    from src.config import get_settings
    from src.exchange_ccxt import ExchangeConnector, FuturesExchangeConnector
    from src.execution_core import ExecutionCore, FuturesExecutionCore
    from src.position_manager import PositionManager
    from src.risk_manager import RiskManager
    from src.leverage_engine import LeverageEngine
    from src.strategies.base import StrategySignal

    cfg = get_settings()

    print("=" * 60)
    print("  FUTURES STARTUP SIMULATION")
    print(f"  Trading Mode: {cfg.trading_mode}")
    print("=" * 60)

    # ── Step 1: Build spot exchange (like server.py does first) ──────────
    print(f"\n--- Step 1: Build spot exchange ---")
    spot_exchange = ExchangeConnector(
        name="binance",
        api_key=cfg.binance_demo_api_key,
        api_secret=cfg.binance_demo_api_secret,
        demo_url=cfg.binance_demo_url,
    )
    await spot_exchange.initialize()
    spot_pairs = spot_exchange.get_usdt_pairs()
    ok(f"Spot exchange: {len(spot_pairs)} pairs (format: {spot_pairs[0] if spot_pairs else '?'})")

    # ── Step 2: Build agents (simulated) ────────────────────────────────
    print(f"\n--- Step 2: Build agents ---")
    execution = ExecutionCore(
        exchange=spot_exchange,
        exchange_mode=cfg.exchange_mode,
    )
    pos_mgr = PositionManager(execution=execution)
    risk_mgr = RiskManager(initial_equity=0.0)
    ok("Agents built (execution, position_mgr, risk_mgr)")

    # ── Step 3: Futures mode setup (mirrors server.py) ──────────────────
    print(f"\n--- Step 3: Futures mode setup ---")
    _is_futures = cfg.trading_mode.lower() == "futures"
    if not _is_futures:
        fail(f"TRADING_MODE is '{cfg.trading_mode}', expected 'futures'. Set in .env")
        await spot_exchange.exchange.close()
        return

    futures_exchange = FuturesExchangeConnector(
        name="binance",
        api_key=cfg.binance_futures_testnet_api_key,
        api_secret=cfg.binance_futures_testnet_api_secret,
        futures_url=cfg.binance_futures_testnet_url,
        default_leverage=cfg.futures_default_leverage,
        margin_type=cfg.futures_margin_type,
    )
    await futures_exchange.initialize()
    ok(f"Futures exchange initialized: {futures_exchange.markets_loaded}")

    futures_pairs = futures_exchange.get_usdt_pairs()
    ok(f"Futures pairs: {len(futures_pairs)} (format: {futures_pairs[0] if futures_pairs else '?'})")

    futures_execution = FuturesExecutionCore(
        exchange=futures_exchange,
        exchange_mode=cfg.exchange_mode,
        max_retries=cfg.max_sell_retries,
    )
    ok("FuturesExecutionCore created")

    leverage_engine = LeverageEngine(
        default_leverage=cfg.futures_default_leverage,
        max_leverage=cfg.futures_max_leverage,
        min_leverage=cfg.futures_min_leverage,
    )
    ok(f"LeverageEngine: default={cfg.futures_default_leverage}x max={cfg.futures_max_leverage}x")

    # ── Step 4: Re-wire (like server.py) ────────────────────────────────
    print(f"\n--- Step 4: Re-wire agents to futures ---")
    exchange = futures_exchange  # mirrors: _exchange = _futures_exchange
    execution = futures_execution
    pos_mgr.execution = futures_execution
    ok("Exchange, execution, position_manager re-wired")

    # ── Step 5: Fetch equity (like _update_equity) ──────────────────────
    print(f"\n--- Step 5: Fetch futures equity ---")
    try:
        balance = await exchange.fetch_balance()
        usdt = balance.get("USDT", {})
        total_usd = float(usdt.get("total", 0.0) or 0.0)
        free_usd = float(usdt.get("free", 0.0) or 0.0)
        if total_usd > 0:
            ok(f"Equity: ${total_usd:.2f} (free: ${free_usd:.2f})")
        else:
            fail(f"Equity is $0 — balance: {usdt}")
    except Exception as e:
        fail(f"Equity fetch: {e}")
        total_usd = 0

    # Detect account tier
    if total_usd > 0:
        tier = risk_mgr.detect_account_tier(total_usd)
        ok(f"Account tier: {tier}")

    # ── Step 6: Symbol compatibility check ──────────────────────────────
    print(f"\n--- Step 6: Symbol compatibility ---")
    test_symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
    for sym in test_symbols:
        try:
            ticker = await exchange.exchange.fetch_ticker(sym)
            ok(f"{sym}: ${ticker['last']:.2f}")
        except Exception as e:
            fail(f"{sym}: {e}")

    # Test OHLCV fetch (used by strategies)
    print(f"\n--- Step 7: OHLCV fetch for strategies ---")
    try:
        candles = await exchange.fetch_ohlcv("BTC/USDT:USDT", "5m", limit=50)
        ok(f"BTC/USDT:USDT 5m candles: {len(candles)} bars")
        if candles:
            last = candles[-1]
            ok(f"  Last candle: O={last[1]:.2f} H={last[2]:.2f} L={last[3]:.2f} C={last[4]:.2f} V={last[5]:.2f}")
    except Exception as e:
        fail(f"OHLCV fetch: {e}")

    try:
        candles_15m = await exchange.fetch_ohlcv("ETH/USDT:USDT", "15m", limit=50)
        ok(f"ETH/USDT:USDT 15m candles: {len(candles_15m)} bars")
    except Exception as e:
        fail(f"ETH 15m: {e}")

    # ── Step 8: Funding rates ───────────────────────────────────────────
    print(f"\n--- Step 8: Funding rates ---")
    try:
        fr_symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
        rates = await futures_exchange.fetch_funding_rates(fr_symbols)
        for sym, rate in rates.items():
            ok(f"Funding {sym}: {rate:.6f}")
    except Exception as e:
        fail(f"Funding rates: {e}")

    # ── Step 9: Position lifecycle test ──────────────────────────────────
    print(f"\n--- Step 9: Simulated position lifecycle ---")
    # Create a signal, size it, and verify the pipeline works
    signal = StrategySignal(
        symbol="BTC/USDT:USDT",
        strategy="scalper",
        direction="long",
        score=70,
        entry_price=float((await exchange.exchange.fetch_ticker("BTC/USDT:USDT"))["last"]),
        stop_loss=0, stop_loss_pct=1.5,
        take_profit_1=0, take_profit_2=0,
        tp1_pct=0.5, tp2_pct=1.0,
        confidence=0.72,
        vol_usd=10_000_000,
        timeframe="5m",
        setup_type="scalp_long",
        reason="test signal",
        leverage=0,
    )
    signal.stop_loss = signal.entry_price * 0.985
    signal.take_profit_1 = signal.entry_price * 1.005
    signal.take_profit_2 = signal.entry_price * 1.01

    lev = leverage_engine.compute_leverage(
        signal_score=signal.score, confidence=signal.confidence,
        regime="bull", vol_usd_24h=signal.vol_usd, direction="long",
    )
    lev = leverage_engine.adjust_for_account_tier(lev, total_usd)
    ok(f"Leverage: {lev}x (for ${total_usd:.0f} account)")

    size = risk_mgr.compute_futures_position_size(
        symbol=signal.symbol, current_equity=total_usd,
        stop_loss_pct=signal.stop_loss_pct, leverage=lev,
        posterior=signal.confidence, vol_usd=signal.vol_usd,
    )
    ok(f"Size: ${size:.2f} notional ({size/lev:.2f} margin × {lev}x)")

    setup = signal.to_setup_dict()
    setup["leverage"] = lev
    setup["direction"] = "long"
    assert setup["leverage"] == lev
    assert setup["symbol"] == "BTC/USDT:USDT"
    ok(f"Setup dict: symbol={setup['symbol']} dir={setup['direction']} lev={setup['leverage']}")

    # ── Step 10: Real tiny order test ───────────────────────────────────
    print(f"\n--- Step 10: Live order sanity check ---")
    try:
        await futures_exchange.prepare_symbol("BTC/USDT:USDT", lev)
        order = await futures_exchange.open_long("BTC/USDT:USDT", 0.001, leverage=lev)
        ok(f"Opened BTC long: order={order.get('id')} lev={lev}x")
        await asyncio.sleep(1)
        close = await futures_exchange.close_long("BTC/USDT:USDT", 0.001)
        ok(f"Closed BTC long: order={close.get('id')}")
    except Exception as e:
        fail(f"Live order: {e}")

    # ── Cleanup ─────────────────────────────────────────────────────────
    await futures_exchange.exchange.close()
    await spot_exchange.exchange.close()

    # ── Results ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  STARTUP SIMULATION: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    if FAIL_COUNT == 0:
        print("  BOT IS READY FOR FUTURES TRADING")
    else:
        print(f"  {FAIL_COUNT} issues to fix before going live")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
