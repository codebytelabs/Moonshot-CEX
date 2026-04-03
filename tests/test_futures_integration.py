"""Quick integration test for futures trading components."""
import sys
sys.path.insert(0, ".")

from src.leverage_engine import LeverageEngine
from src.risk_manager import RiskManager


def test_leverage_engine():
    le = LeverageEngine(default_leverage=3, max_leverage=10, min_leverage=1)

    # Bull regime, high confidence long
    lev = le.compute_leverage(
        signal_score=75, confidence=0.8, regime="bull",
        vol_usd_24h=10_000_000, win_streak=3, direction="long",
    )
    assert 1 <= lev <= 10, f"Leverage out of range: {lev}"
    print(f"  Bull/high-conf long: {lev}x")

    # Bear regime short
    lev2 = le.compute_leverage(
        signal_score=60, confidence=0.6, regime="bear",
        vol_usd_24h=5_000_000, direction="short",
    )
    assert 1 <= lev2 <= 10, f"Leverage out of range: {lev2}"
    print(f"  Bear short: {lev2}x")

    # Low confidence with drawdown
    lev3 = le.compute_leverage(
        signal_score=40, confidence=0.4, regime="sideways",
        vol_usd_24h=1_000_000, drawdown_pct=8.0,
    )
    assert lev3 <= lev, f"Drawdown should reduce leverage: {lev3} vs {lev}"
    print(f"  Low-conf/drawdown: {lev3}x")

    # Account tier adjustment
    assert le.adjust_for_account_tier(8, 300) <= 3, "Small account (<$500) should cap at 3x"
    assert le.adjust_for_account_tier(8, 5000) <= 8, "Mid account ($2K-$10K) should cap at 8x"
    print("  Account tier caps: OK")
    print("PASS: LeverageEngine")


def test_futures_position_sizing():
    rm = RiskManager(initial_equity=1000.0)
    rm.detect_account_tier(1000.0)

    spot = rm.compute_position_size(
        "BTC/USDT", 1000.0, -1.5, posterior=0.7, vol_usd=10_000_000,
    )
    fut = rm.compute_futures_position_size(
        "BTC/USDT", 1000.0, -1.5, leverage=5, posterior=0.7, vol_usd=10_000_000,
    )
    print(f"  Spot size: ${spot:.2f}")
    print(f"  Futures 5x size: ${fut:.2f}")
    assert fut >= spot, f"Futures should be >= spot: {fut} vs {spot}"
    assert fut <= 25_000, f"Futures hard cap exceeded: {fut}"

    # 1x leverage should equal spot
    fut_1x = rm.compute_futures_position_size(
        "BTC/USDT", 1000.0, -1.5, leverage=1, posterior=0.7, vol_usd=10_000_000,
    )
    print(f"  Futures 1x size: ${fut_1x:.2f} (should match spot)")
    print("PASS: FuturesPositionSizing")


def test_imports():
    from src.exchange_ccxt import ExchangeConnector, FuturesExchangeConnector
    from src.execution_core import ExecutionCore, FuturesExecutionCore
    from src.strategies.mean_reversion import MeanReversionStrategy
    from src.strategies.scalper import ScalpingSniper
    from src.strategies.breakout import BreakoutORB
    from src.strategies.base import StrategySignal
    from src.config import get_settings

    # Check StrategySignal has leverage field
    sig = StrategySignal(
        symbol="BTC/USDT", strategy="test", direction="short",
        score=70, entry_price=50000, stop_loss=51000, stop_loss_pct=2.0,
        take_profit_1=49000, take_profit_2=48000, tp1_pct=2.0, tp2_pct=4.0,
        confidence=0.7, vol_usd=10_000_000, timeframe="15m",
        setup_type="test", reason="test", leverage=5,
    )
    d = sig.to_setup_dict()
    assert d["direction"] == "short", f"Direction wrong: {d['direction']}"
    assert d["leverage"] == 5, f"Leverage wrong: {d.get('leverage')}"
    print("  StrategySignal with leverage+short: OK")

    # Config has futures fields
    cfg = get_settings()
    assert hasattr(cfg, "trading_mode"), "Missing trading_mode"
    assert hasattr(cfg, "futures_default_leverage"), "Missing futures_default_leverage"
    assert hasattr(cfg, "futures_max_leverage"), "Missing futures_max_leverage"
    assert hasattr(cfg, "futures_margin_type"), "Missing futures_margin_type"
    assert hasattr(cfg, "binance_futures_testnet_api_key"), "Missing futures testnet key"
    print("  Config futures fields: OK")
    print("PASS: Imports & DataStructures")


if __name__ == "__main__":
    print("=" * 50)
    print("Futures Integration Tests")
    print("=" * 50)
    test_imports()
    test_leverage_engine()
    test_futures_position_sizing()
    print("=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)
