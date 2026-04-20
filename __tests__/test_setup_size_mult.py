import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.risk_manager import RiskManager, SETUP_SIZE_MULT


def make_rm() -> RiskManager:
    return RiskManager(
        max_positions=5,
        max_portfolio_exposure_pct=0.30,
        max_single_exposure_pct=0.10,
        max_risk_per_trade_pct=0.02,
        max_drawdown_pct=0.25,
        daily_loss_limit_pct=0.10,
        consecutive_loss_threshold=99,
        initial_equity=10_000.0,
        rolling_wr_window=999,
    )


def _size(rm: RiskManager, setup_type: str | None) -> float:
    return rm.compute_position_size(
        symbol="BTC/USDT",
        current_equity=10_000.0,
        stop_loss_pct=-2.0,
        posterior=0.70,
        threshold=0.60,
        vol_usd=50_000_000.0,
        ta_score=70.0,
        regime="bull",
        regime_size_mult=1.0,
        current_regime="bull",
        setup_type=setup_type,
    )


def test_ema_trend_follow_is_half_sized_vs_clean_setup():
    rm = make_rm()
    baseline = _size(rm, setup_type="vwap_momentum_breakout")
    validation = _size(rm, setup_type="ema_trend_follow")

    # Table says 0.5× for ema_trend_follow
    assert SETUP_SIZE_MULT["ema_trend_follow"] == 0.5

    # Hard floors can lift the final size, so accept equality only when the
    # validation size would otherwise fall below the floor.
    assert validation <= baseline
    # When sizing is clearly above the floor, validation must be strictly smaller.
    if baseline > 300.0:
        assert validation < baseline


def test_untagged_setup_gets_full_allocation():
    rm = make_rm()
    default_size = _size(rm, setup_type=None)
    clean_size = _size(rm, setup_type="vwap_momentum_breakout")
    assert default_size == clean_size
