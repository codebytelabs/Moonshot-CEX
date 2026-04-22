"""Unit tests for RiskManager."""
import pytest
import time
from unittest.mock import MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.risk_manager import RiskManager


def make_rm(
    max_positions=5,
    max_portfolio_exposure_pct=0.30,
    max_single_exposure_pct=0.08,
    max_risk_per_trade_pct=0.01,
    max_drawdown_pct=0.15,
    daily_loss_limit_pct=0.05,
    consecutive_loss_threshold=3,
    consecutive_loss_pause_minutes=10,
    kelly_fraction=0.5,
    max_kelly_fraction=0.25,
    min_trades_for_kelly=30,
    initial_equity=1000.0,
) -> RiskManager:
    return RiskManager(
        max_positions=max_positions,
        max_portfolio_exposure_pct=max_portfolio_exposure_pct,
        max_single_exposure_pct=max_single_exposure_pct,
        max_risk_per_trade_pct=max_risk_per_trade_pct,
        max_drawdown_pct=max_drawdown_pct,
        daily_loss_limit_pct=daily_loss_limit_pct,
        consecutive_loss_threshold=consecutive_loss_threshold,
        consecutive_loss_pause_minutes=consecutive_loss_pause_minutes,
        kelly_fraction=kelly_fraction,
        max_kelly_fraction=max_kelly_fraction,
        min_trades_for_kelly=min_trades_for_kelly,
        initial_equity=initial_equity,
    )


def test_can_open_position_allowed():
    rm = make_rm()
    allowed, reason = rm.can_open_position(
        current_equity=1000.0,
        open_count=0,
        current_exposure_usd=0.0,
    )
    assert allowed is True


def test_can_open_blocks_max_positions():
    rm = make_rm(max_positions=5)
    allowed, reason = rm.can_open_position(
        current_equity=1000.0,
        open_count=5,
        current_exposure_usd=0.0,
    )
    assert allowed is False
    assert "max_positions" in reason


def test_can_open_blocks_max_exposure():
    rm = make_rm(max_portfolio_exposure_pct=0.30)
    allowed, reason = rm.can_open_position(
        current_equity=1000.0,
        open_count=2,
        current_exposure_usd=350.0,
    )
    assert allowed is False
    assert "max_exposure" in reason


def test_can_open_blocks_daily_loss_limit():
    rm = make_rm(daily_loss_limit_pct=0.05, initial_equity=1000.0)
    rm._day_start_equity = 1000.0
    allowed, reason = rm.can_open_position(
        current_equity=940.0,
        open_count=0,
        current_exposure_usd=0.0,
    )
    assert allowed is False
    assert "daily_loss" in reason


def test_can_open_blocks_max_drawdown():
    rm = make_rm(max_drawdown_pct=0.10, daily_loss_limit_pct=0.50, initial_equity=1000.0)
    rm.peak_equity = 1000.0
    rm._day_start_equity = 880.0
    allowed, reason = rm.can_open_position(
        current_equity=880.0,
        open_count=0,
        current_exposure_usd=0.0,
    )
    assert allowed is False
    assert "drawdown" in reason


def test_consecutive_loss_pause():
    rm = make_rm(consecutive_loss_threshold=3, consecutive_loss_pause_minutes=10)
    rm.record_trade(pnl_usd=-10.0, pnl_pct=-0.01, r_multiple=-0.5)
    rm.record_trade(pnl_usd=-10.0, pnl_pct=-0.01, r_multiple=-0.5)
    rm.record_trade(pnl_usd=-10.0, pnl_pct=-0.01, r_multiple=-0.5)
    allowed, reason = rm.can_open_position(
        current_equity=970.0,
        open_count=0,
        current_exposure_usd=0.0,
    )
    assert allowed is False
    assert "pause" in reason


def test_consecutive_losses_reset_on_win():
    rm = make_rm(consecutive_loss_threshold=3)
    rm.record_trade(pnl_usd=-10.0, pnl_pct=-0.01, r_multiple=-0.5)
    rm.record_trade(pnl_usd=-10.0, pnl_pct=-0.01, r_multiple=-0.5)
    assert rm._consecutive_losses == 2
    rm.record_trade(pnl_usd=20.0, pnl_pct=0.02, r_multiple=2.0)
    assert rm._consecutive_losses == 0


def test_win_rate_calculation():
    rm = make_rm()
    rm._trade_history = [
        {"won": True, "pnl_usd": 10, "pnl_pct": 0.01, "r_multiple": 1.0},
        {"won": False, "pnl_usd": -5, "pnl_pct": -0.005, "r_multiple": -0.5},
        {"won": True, "pnl_usd": 20, "pnl_pct": 0.02, "r_multiple": 2.0},
        {"won": False, "pnl_usd": -3, "pnl_pct": -0.003, "r_multiple": -0.3},
        {"won": True, "pnl_usd": 15, "pnl_pct": 0.015, "r_multiple": 1.5},
    ]
    health = rm.check_portfolio_health(current_equity=1000.0)
    assert abs(health["win_rate"] - 0.6) < 0.01


def test_compute_position_size_respects_single_exposure():
    rm = make_rm(max_single_exposure_pct=0.08, initial_equity=1000.0)
    size = rm.compute_position_size(
        symbol="BTC/USDT",
        current_equity=1000.0,
        stop_loss_pct=-18.0,
    )
    assert size <= 1000.0 * 0.25
    assert size > 0


def test_setup_size_mult_halves_ema_ribbon_pullback():
    """ema_ribbon_pullback went 0W/5L (-$167) → must ship at half sizing."""
    from src.risk_manager import SETUP_SIZE_MULT

    assert SETUP_SIZE_MULT.get("ema_ribbon_pullback") == 0.5
    rm = make_rm()
    assert rm.get_effective_setup_size_multiplier("ema_ribbon_pullback") == 0.5
    # A setup without an entry should default to 1.0 (no sizing penalty).
    assert rm.get_effective_setup_size_multiplier("breakout_orb") == 1.0


def test_setup_circuit_breaker_covers_ema_ribbon_pullback():
    """Losing streak on ema_ribbon_pullback must trigger a per-setup pause."""
    from src.risk_manager import SETUP_CIRCUIT_BREAKERS

    cfg = SETUP_CIRCUIT_BREAKERS.get("ema_ribbon_pullback")
    assert cfg is not None
    assert cfg["window"] == 5
    assert cfg["max_wr"] == 0.20
    assert cfg["pause_minutes"] == 120

    # Raise consecutive_loss_threshold + daily_loss_limit so only the per-setup
    # circuit breaker can block; otherwise global guards trip first.
    rm = make_rm(
        consecutive_loss_threshold=99,
        daily_loss_limit_pct=0.50,
        initial_equity=10_000.0,
    )
    for _ in range(5):
        rm.record_trade(
            pnl_usd=-10.0,
            pnl_pct=-0.001,
            r_multiple=-0.5,
            setup_type="ema_ribbon_pullback",
        )
    assert rm._setup_pause_until.get("ema_ribbon_pullback", 0) > time.time()
    allowed, reason = rm.can_open_position(
        current_equity=9_950.0,
        open_count=0,
        current_exposure_usd=0.0,
        setup_type="ema_ribbon_pullback",
    )
    assert allowed is False
    assert "setup_circuit_breaker:ema_ribbon_pullback" in reason
    # Other setups should still be allowed to trade.
    allowed_other, _ = rm.can_open_position(
        current_equity=9_950.0,
        open_count=0,
        current_exposure_usd=0.0,
        setup_type="vwap_momentum_breakout",
    )
    assert allowed_other is True


def test_setup_size_mult_halves_bb_squeeze_breakout():
    """bb_squeeze_breakout went 0W/3L (-$33.71) in bull → must ship at half sizing."""
    from src.risk_manager import SETUP_SIZE_MULT

    assert SETUP_SIZE_MULT.get("bb_squeeze_breakout") == 0.5
    rm = make_rm()
    assert rm.get_effective_setup_size_multiplier("bb_squeeze_breakout") == 0.5


def test_setup_size_mult_halves_bb_mean_reversion():
    """bb_mean_reversion went 0W/1L (-$8.99) in bull → must ship at half sizing."""
    from src.risk_manager import SETUP_SIZE_MULT

    assert SETUP_SIZE_MULT.get("bb_mean_reversion") == 0.5
    rm = make_rm()
    assert rm.get_effective_setup_size_multiplier("bb_mean_reversion") == 0.5


def test_setup_circuit_breaker_covers_bb_squeeze_breakout():
    """Losing streak on bb_squeeze_breakout must trigger a per-setup pause."""
    from src.risk_manager import SETUP_CIRCUIT_BREAKERS

    cfg = SETUP_CIRCUIT_BREAKERS.get("bb_squeeze_breakout")
    assert cfg is not None
    assert cfg["window"] == 5
    assert cfg["max_wr"] == 0.20
    assert cfg["pause_minutes"] == 120

    rm = make_rm(
        consecutive_loss_threshold=99,
        daily_loss_limit_pct=0.50,
        initial_equity=10_000.0,
    )
    for _ in range(5):
        rm.record_trade(
            pnl_usd=-10.0,
            pnl_pct=-0.001,
            r_multiple=-0.5,
            setup_type="bb_squeeze_breakout",
        )
    assert rm._setup_pause_until.get("bb_squeeze_breakout", 0) > time.time()
    allowed, reason = rm.can_open_position(
        current_equity=9_950.0,
        open_count=0,
        current_exposure_usd=0.0,
        setup_type="bb_squeeze_breakout",
    )
    assert allowed is False
    assert "setup_circuit_breaker:bb_squeeze_breakout" in reason


def test_setup_circuit_breaker_covers_bb_mean_reversion():
    """Losing streak on bb_mean_reversion must trigger a per-setup pause."""
    from src.risk_manager import SETUP_CIRCUIT_BREAKERS

    cfg = SETUP_CIRCUIT_BREAKERS.get("bb_mean_reversion")
    assert cfg is not None
    assert cfg["window"] == 5
    assert cfg["max_wr"] == 0.20
    assert cfg["pause_minutes"] == 120

    rm = make_rm(
        consecutive_loss_threshold=99,
        daily_loss_limit_pct=0.50,
        initial_equity=10_000.0,
    )
    for _ in range(5):
        rm.record_trade(
            pnl_usd=-10.0,
            pnl_pct=-0.001,
            r_multiple=-0.5,
            setup_type="bb_mean_reversion",
        )
    assert rm._setup_pause_until.get("bb_mean_reversion", 0) > time.time()
    allowed, reason = rm.can_open_position(
        current_equity=9_950.0,
        open_count=0,
        current_exposure_usd=0.0,
        setup_type="bb_mean_reversion",
    )
    assert allowed is False
    assert "setup_circuit_breaker:bb_mean_reversion" in reason


def test_setup_size_mult_halves_momentum():
    """legacy 'momentum' setup went 2W/4L (PF=0.65) in 24h → half-size."""
    from src.risk_manager import SETUP_SIZE_MULT

    assert SETUP_SIZE_MULT.get("momentum") == 0.5
    rm = make_rm()
    assert rm.get_effective_setup_size_multiplier("momentum") == 0.5


def test_setup_circuit_breaker_covers_momentum():
    """Losing streak on legacy 'momentum' must trigger a per-setup pause."""
    from src.risk_manager import SETUP_CIRCUIT_BREAKERS

    cfg = SETUP_CIRCUIT_BREAKERS.get("momentum")
    assert cfg is not None
    assert cfg["window"] == 5
    assert cfg["max_wr"] == 0.20
    assert cfg["pause_minutes"] == 120

    rm = make_rm(
        consecutive_loss_threshold=99,
        daily_loss_limit_pct=0.50,
        initial_equity=10_000.0,
    )
    for _ in range(5):
        rm.record_trade(
            pnl_usd=-10.0,
            pnl_pct=-0.001,
            r_multiple=-0.5,
            setup_type="momentum",
        )
    assert rm._setup_pause_until.get("momentum", 0) > time.time()
    allowed, reason = rm.can_open_position(
        current_equity=9_950.0,
        open_count=0,
        current_exposure_usd=0.0,
        setup_type="momentum",
    )
    assert allowed is False
    assert "setup_circuit_breaker:momentum" in reason


def test_setup_size_mult_boosts_vwap_momentum_breakout():
    """Only positive-expectancy setup gets a modest 1.15x boost.

    Live 24h: 2W/1L, +$47.48, PF=2.62. Effective must respect the 1.25 clamp.
    """
    from src.risk_manager import SETUP_SIZE_MULT

    assert SETUP_SIZE_MULT.get("vwap_momentum_breakout") == 1.15
    rm = make_rm()
    mult = rm.get_effective_setup_size_multiplier("vwap_momentum_breakout")
    assert mult == 1.15
    assert 1.0 < mult <= 1.25
