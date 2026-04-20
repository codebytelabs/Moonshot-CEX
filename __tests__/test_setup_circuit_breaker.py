import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.risk_manager import RiskManager, SETUP_CIRCUIT_BREAKERS


def make_rm() -> RiskManager:
    return RiskManager(
        max_positions=5,
        max_portfolio_exposure_pct=0.30,
        max_single_exposure_pct=0.10,
        max_risk_per_trade_pct=0.01,
        max_drawdown_pct=0.20,
        daily_loss_limit_pct=0.50,
        consecutive_loss_threshold=99,
        initial_equity=1000.0,
        rolling_wr_window=999,
    )


def test_unknown_setup_is_never_paused_by_per_setup_breaker():
    rm = make_rm()
    for _ in range(10):
        rm.record_trade(pnl_usd=-5.0, pnl_pct=-0.5, r_multiple=-0.5, setup_type="new_setup")

    allowed, reason = rm.can_open_position(
        current_equity=1000.0,
        open_count=0,
        current_exposure_usd=0.0,
        setup_type="new_setup",
    )
    assert allowed, f"unknown setup should not be breaker-paused, got: {reason}"


def test_ema_trend_follow_breaker_pauses_after_losing_window():
    rm = make_rm()
    cfg = SETUP_CIRCUIT_BREAKERS["ema_trend_follow"]
    for _ in range(cfg["window"]):
        rm.record_trade(
            pnl_usd=-10.0,
            pnl_pct=-0.5,
            r_multiple=-0.5,
            setup_type="ema_trend_follow",
        )

    allowed, reason = rm.can_open_position(
        current_equity=1000.0,
        open_count=0,
        current_exposure_usd=0.0,
        setup_type="ema_trend_follow",
    )
    assert not allowed
    assert "setup_circuit_breaker:ema_trend_follow" in reason


def test_breaker_only_blocks_same_setup():
    rm = make_rm()
    cfg = SETUP_CIRCUIT_BREAKERS["ema_trend_follow"]
    for _ in range(cfg["window"]):
        rm.record_trade(
            pnl_usd=-10.0,
            pnl_pct=-0.5,
            r_multiple=-0.5,
            setup_type="ema_trend_follow",
        )

    allowed, reason = rm.can_open_position(
        current_equity=1000.0,
        open_count=0,
        current_exposure_usd=0.0,
        setup_type="vwap_momentum_breakout",
    )
    assert allowed, f"other setups should remain tradable, got: {reason}"
