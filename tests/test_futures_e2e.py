"""
End-to-end futures trading test on Binance Testnet.

Tests:
  1. Paper mode: long + short entry/exit via FuturesExecutionCore
  2. Live testnet: real order placement (tiny BTC long, then close)
  3. Full pipeline: strategy signal → leverage engine → sizing → entry
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from src.config import get_settings
from src.exchange_ccxt import FuturesExchangeConnector
from src.execution_core import FuturesExecutionCore
from src.position_manager import PositionManager
from src.risk_manager import RiskManager
from src.leverage_engine import LeverageEngine
from src.strategies.base import StrategySignal

cfg = get_settings()
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


async def build_futures_stack():
    """Build the full futures trading stack."""
    connector = FuturesExchangeConnector(
        name="binance",
        api_key=cfg.binance_futures_testnet_api_key,
        api_secret=cfg.binance_futures_testnet_api_secret,
        futures_url=cfg.binance_futures_testnet_url,
        default_leverage=cfg.futures_default_leverage,
        margin_type=cfg.futures_margin_type,
    )
    await connector.initialize()

    execution = FuturesExecutionCore(
        exchange=connector,
        exchange_mode="demo",
        max_retries=3,
    )

    risk_mgr = RiskManager(initial_equity=5000.0)
    risk_mgr.detect_account_tier(5000.0)

    pos_mgr = PositionManager(execution=execution)

    lev_engine = LeverageEngine(
        default_leverage=cfg.futures_default_leverage,
        max_leverage=cfg.futures_max_leverage,
        min_leverage=cfg.futures_min_leverage,
    )

    return connector, execution, risk_mgr, pos_mgr, lev_engine


# ── Test 1: Paper Mode Long + Short ────────────────────────────────────────

async def test_paper_mode():
    print(f"\n{'='*60}")
    print("  TEST 1: Paper Mode — Long & Short Entry/Exit")
    print(f"{'='*60}")

    connector = FuturesExchangeConnector(
        name="binance",
        api_key=cfg.binance_futures_testnet_api_key,
        api_secret=cfg.binance_futures_testnet_api_secret,
        futures_url=cfg.binance_futures_testnet_url,
    )
    await connector.initialize()

    paper_exec = FuturesExecutionCore(
        exchange=connector,
        exchange_mode="paper",
    )

    # Paper long entry
    try:
        fill = await paper_exec.enter_position(
            symbol="BTC/USDT:USDT", side="buy", amount_usd=500,
            price=67000.0, setup_type="test_long", leverage=5, direction="long",
        )
        assert fill["direction"] == "long", f"Expected long, got {fill.get('direction')}"
        assert fill["leverage"] == 5, f"Expected 5x, got {fill.get('leverage')}"
        assert fill["filled_price"] > 0
        ok(f"Paper LONG entry: ${fill['amount_usd']:.2f} @ {fill['filled_price']:.2f} {fill['leverage']}x")
    except Exception as e:
        fail(f"Paper LONG entry: {e}")

    # Paper short entry
    try:
        fill = await paper_exec.enter_position(
            symbol="ETH/USDT:USDT", side="sell", amount_usd=300,
            price=3500.0, setup_type="test_short", leverage=3, direction="short",
        )
        assert fill["direction"] == "short"
        assert fill["leverage"] == 3
        ok(f"Paper SHORT entry: ${fill['amount_usd']:.2f} @ {fill['filled_price']:.2f} {fill['leverage']}x")
    except Exception as e:
        fail(f"Paper SHORT entry: {e}")

    # Paper long exit
    try:
        fill = await paper_exec.exit_position(
            symbol="BTC/USDT:USDT", amount=0.007, price=67500.0,
            reason="trailing_stop", direction="long",
        )
        ok(f"Paper LONG exit: {fill.get('reason', 'ok')}")
    except Exception as e:
        fail(f"Paper LONG exit: {e}")

    # Paper short exit
    try:
        fill = await paper_exec.exit_position(
            symbol="ETH/USDT:USDT", amount=0.085, price=3400.0,
            reason="take_profit", direction="short",
        )
        ok(f"Paper SHORT exit: {fill.get('reason', 'ok')}")
    except Exception as e:
        fail(f"Paper SHORT exit: {e}")

    await connector.exchange.close()


# ── Test 2: Live Testnet Order ─────────────────────────────────────────────

async def test_live_testnet_order():
    print(f"\n{'='*60}")
    print("  TEST 2: Live Testnet — Real Futures Order (tiny BTC long)")
    print(f"{'='*60}")

    connector, execution, risk_mgr, pos_mgr, lev_engine = await build_futures_stack()

    # Get current BTC price
    try:
        ticker = await connector.exchange.fetch_ticker("BTC/USDT:USDT")
        btc_price = ticker["last"]
        ok(f"BTC price: ${btc_price:.2f}")
    except Exception as e:
        fail(f"Fetch BTC ticker: {e}")
        await connector.exchange.close()
        return

    # Check balance before
    try:
        bal_before = await connector.fetch_futures_balance()
        ok(f"Balance before: ${bal_before['total']:.2f} (free: ${bal_before['free']:.2f})")
    except Exception as e:
        fail(f"Balance before: {e}")

    # Set leverage + margin
    try:
        prepared = await connector.prepare_symbol("BTC/USDT:USDT", 3)
        ok(f"Prepared BTC/USDT:USDT: leverage=3x margin=ISOLATED → {prepared}")
    except Exception as e:
        fail(f"Prepare symbol: {e}")

    # Open a tiny long position (~$30 notional, minimum allowed)
    min_amount = 0.001  # BTC minimum on futures testnet
    try:
        order = await connector.open_long("BTC/USDT:USDT", min_amount, leverage=3)
        order_id = order.get("id", "?")
        ok(f"OPENED LONG: order_id={order_id} amount={min_amount} BTC @ ~${btc_price:.2f}")
    except Exception as e:
        fail(f"Open long: {e}")
        await connector.exchange.close()
        return

    # Wait a moment then check positions
    await asyncio.sleep(2)
    try:
        positions = await connector.fetch_positions(["BTC/USDT:USDT"])
        open_pos = [p for p in positions if abs(float(p.get("contracts", 0))) > 0]
        if open_pos:
            pos = open_pos[0]
            ok(f"Position confirmed: {pos.get('symbol')} contracts={pos.get('contracts')} "
               f"side={pos.get('side')} leverage={pos.get('leverage')} "
               f"entryPrice={pos.get('entryPrice')}")
        else:
            fail("Position not found after opening")
    except Exception as e:
        fail(f"Fetch positions: {e}")

    # Close the position
    try:
        close_order = await connector.close_long("BTC/USDT:USDT", min_amount)
        ok(f"CLOSED LONG: order_id={close_order.get('id', '?')}")
    except Exception as e:
        fail(f"Close long: {e}")

    # Check balance after
    await asyncio.sleep(1)
    try:
        bal_after = await connector.fetch_futures_balance()
        pnl = bal_after["total"] - bal_before["total"]
        ok(f"Balance after: ${bal_after['total']:.2f} (PnL: ${pnl:+.4f})")
    except Exception as e:
        fail(f"Balance after: {e}")

    await connector.exchange.close()


# ── Test 3: Live Testnet Short Order ───────────────────────────────────────

async def test_live_testnet_short():
    print(f"\n{'='*60}")
    print("  TEST 3: Live Testnet — Real Futures Short (tiny ETH)")
    print(f"{'='*60}")

    connector, execution, risk_mgr, pos_mgr, lev_engine = await build_futures_stack()

    try:
        ticker = await connector.exchange.fetch_ticker("ETH/USDT:USDT")
        eth_price = ticker["last"]
        ok(f"ETH price: ${eth_price:.2f}")
    except Exception as e:
        fail(f"Fetch ETH ticker: {e}")
        await connector.exchange.close()
        return

    bal_before = await connector.fetch_futures_balance()

    # Open short
    min_amount = 0.01  # ETH minimum
    try:
        await connector.prepare_symbol("ETH/USDT:USDT", 5)
        order = await connector.open_short("ETH/USDT:USDT", min_amount, leverage=5)
        ok(f"OPENED SHORT: order_id={order.get('id', '?')} ETH amount={min_amount}")
    except Exception as e:
        fail(f"Open short: {e}")
        await connector.exchange.close()
        return

    await asyncio.sleep(2)

    # Verify position
    try:
        positions = await connector.fetch_positions(["ETH/USDT:USDT"])
        open_pos = [p for p in positions if abs(float(p.get("contracts", 0))) > 0]
        if open_pos:
            pos = open_pos[0]
            ok(f"SHORT position: {pos.get('symbol')} contracts={pos.get('contracts')} "
               f"side={pos.get('side')} leverage={pos.get('leverage')}")
        else:
            fail("Short position not found")
    except Exception as e:
        fail(f"Fetch short position: {e}")

    # Close short
    try:
        close_order = await connector.close_short("ETH/USDT:USDT", min_amount)
        ok(f"CLOSED SHORT: order_id={close_order.get('id', '?')}")
    except Exception as e:
        fail(f"Close short: {e}")

    await asyncio.sleep(1)
    bal_after = await connector.fetch_futures_balance()
    pnl = bal_after["total"] - bal_before["total"]
    ok(f"Short round-trip PnL: ${pnl:+.4f}")

    await connector.exchange.close()


# ── Test 4: Full Pipeline — Signal → Leverage → Sizing → Entry ────────────

async def test_full_pipeline():
    print(f"\n{'='*60}")
    print("  TEST 4: Full Pipeline — Signal → Leverage → Sizing → Entry")
    print(f"{'='*60}")

    connector, execution, risk_mgr, pos_mgr, lev_engine = await build_futures_stack()

    # Simulate a strategy signal
    ticker = await connector.exchange.fetch_ticker("BTC/USDT:USDT")
    btc_price = ticker["last"]

    signal = StrategySignal(
        symbol="BTC/USDT:USDT",
        strategy="scalper",
        direction="long",
        score=72,
        entry_price=btc_price,
        stop_loss=btc_price * 0.985,
        stop_loss_pct=1.5,
        take_profit_1=btc_price * 1.005,
        take_profit_2=btc_price * 1.01,
        tp1_pct=0.5,
        tp2_pct=1.0,
        confidence=0.75,
        vol_usd=15_000_000,
        timeframe="5m",
        setup_type="scalp_long",
        reason="EMA cross + RSI bounce",
        leverage=0,  # will be computed
    )

    # Step 1: Compute leverage
    equity = 5000.0
    leverage = lev_engine.compute_leverage(
        signal_score=signal.score,
        confidence=signal.confidence,
        regime="bull",
        vol_usd_24h=signal.vol_usd,
        win_streak=2,
        direction=signal.direction,
    )
    leverage = lev_engine.adjust_for_account_tier(leverage, equity)
    ok(f"Leverage computed: {leverage}x")

    # Step 2: Compute futures position size
    size_usd = risk_mgr.compute_futures_position_size(
        symbol=signal.symbol,
        current_equity=equity,
        stop_loss_pct=signal.stop_loss_pct,
        leverage=leverage,
        posterior=signal.confidence,
        vol_usd=signal.vol_usd,
    )
    ok(f"Position size: ${size_usd:.2f} (notional with {leverage}x leverage)")

    # Step 3: Convert signal to setup dict
    setup = signal.to_setup_dict()
    setup["leverage"] = leverage
    ok(f"Setup dict: direction={setup['direction']} leverage={setup['leverage']}")

    # Step 4: Open position via PositionManager
    try:
        pos = await pos_mgr.open_position(
            setup=setup,
            amount_usd=size_usd,
            tier1_r=2.0,
            tier2_r=5.0,
        )
        if pos:
            ok(f"Position opened: {pos.symbol} {pos.side} {pos.leverage}x "
               f"entry={pos.entry_price:.2f} sl={pos.stop_loss:.2f} "
               f"tp1={pos.take_profit_1:.2f} amount=${pos.amount_usd:.2f}")
            # Verify position fields
            assert pos.side == "long", f"Side wrong: {pos.side}"
            assert pos.leverage == leverage, f"Leverage wrong: {pos.leverage}"
            ok("Position fields verified (side, leverage)")
        else:
            fail("Position returned None")
    except Exception as e:
        fail(f"Open position: {e}")

    # Step 5: Check open positions count
    assert pos_mgr.open_count == 1, f"Expected 1 open, got {pos_mgr.open_count}"
    ok(f"Open positions: {pos_mgr.open_count}")

    # Step 6: Close the position (via connector directly to clean up)
    await asyncio.sleep(1)
    try:
        if pos:
            await connector.close_long("BTC/USDT:USDT", pos.amount)
            ok("Testnet position closed (cleanup)")
    except Exception as e:
        # May fail if amount precision is off, that's OK for cleanup
        print(f"  [WARN] Cleanup close: {e}")

    await connector.exchange.close()


# ── Test 5: Short Pipeline ─────────────────────────────────────────────────

async def test_short_pipeline():
    print(f"\n{'='*60}")
    print("  TEST 5: Short Pipeline — Bear signal → Short entry")
    print(f"{'='*60}")

    connector, execution, risk_mgr, pos_mgr, lev_engine = await build_futures_stack()

    ticker = await connector.exchange.fetch_ticker("ETH/USDT:USDT")
    eth_price = ticker["last"]

    signal = StrategySignal(
        symbol="ETH/USDT:USDT",
        strategy="mean_reversion",
        direction="short",
        score=68,
        entry_price=eth_price,
        stop_loss=eth_price * 1.02,
        stop_loss_pct=2.0,
        take_profit_1=eth_price * 0.99,
        take_profit_2=eth_price * 0.98,
        tp1_pct=1.0,
        tp2_pct=2.0,
        confidence=0.7,
        vol_usd=8_000_000,
        timeframe="15m",
        setup_type="overbought_fade",
        reason="RSI overbought + BB upper rejection",
        leverage=0,
    )

    # Compute leverage for short in bear regime
    leverage = lev_engine.compute_leverage(
        signal_score=signal.score,
        confidence=signal.confidence,
        regime="bear",
        vol_usd_24h=signal.vol_usd,
        direction="short",
    )
    leverage = lev_engine.adjust_for_account_tier(leverage, 5000.0)
    ok(f"Short leverage: {leverage}x (bear regime boost)")

    size_usd = risk_mgr.compute_futures_position_size(
        symbol=signal.symbol,
        current_equity=5000.0,
        stop_loss_pct=signal.stop_loss_pct,
        leverage=leverage,
        posterior=signal.confidence,
        vol_usd=signal.vol_usd,
    )
    ok(f"Short size: ${size_usd:.2f}")

    setup = signal.to_setup_dict()
    setup["leverage"] = leverage

    try:
        pos = await pos_mgr.open_position(setup=setup, amount_usd=size_usd)
        if pos:
            ok(f"SHORT opened: {pos.symbol} {pos.side} {pos.leverage}x "
               f"entry={pos.entry_price:.2f} sl={pos.stop_loss:.2f}")
            assert pos.side == "short"
            ok("Short position fields verified")
        else:
            fail("Short position returned None")
    except Exception as e:
        fail(f"Short position: {e}")

    # Cleanup
    await asyncio.sleep(1)
    try:
        if pos:
            await connector.close_short("ETH/USDT:USDT", pos.amount)
            ok("Short position closed (cleanup)")
    except Exception as e:
        print(f"  [WARN] Cleanup: {e}")

    await connector.exchange.close()


async def main():
    print("=" * 60)
    print("  FUTURES E2E TEST SUITE")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Trading Mode: {cfg.trading_mode}")
    print(f"  Futures URL: {cfg.binance_futures_testnet_url}")
    print("=" * 60)

    await test_paper_mode()
    await test_live_testnet_order()
    await test_live_testnet_short()
    await test_full_pipeline()
    await test_short_pipeline()

    print(f"\n{'='*60}")
    print(f"  RESULTS: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    if FAIL_COUNT == 0:
        print("  ALL TESTS PASSED")
    else:
        print(f"  {FAIL_COUNT} FAILURES — check output above")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
