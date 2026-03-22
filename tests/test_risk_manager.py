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
