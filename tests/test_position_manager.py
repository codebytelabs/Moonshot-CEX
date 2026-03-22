"""Unit tests for PositionManager."""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.position_manager import PositionManager, Position
from src.execution_core import ExecutionCore


def make_mock_execution(fill_price=100.0, fill_amount=1.0):
    ex = MagicMock(spec=ExecutionCore)
    ex.mode = "paper"
    ex.enter_position = AsyncMock(return_value={
        "order_id": "test-ord-1",
        "symbol": "BTC/USDT",
        "side": "buy",
        "filled_price": fill_price,
        "filled_amount": fill_amount,
        "amount_usd": fill_price * fill_amount,
        "fee_usd": 0.1,
        "slippage_pct": 0.0,
        "timestamp": int(time.time()),
        "mode": "paper",
    })
    ex.exit_position = AsyncMock(return_value={
        "order_id": "test-ord-2",
        "symbol": "BTC/USDT",
        "side": "sell",
        "filled_price": fill_price,
        "filled_amount": fill_amount,
        "amount_usd": fill_price * fill_amount,
        "fee_usd": 0.1,
        "slippage_pct": 0.0,
        "timestamp": int(time.time()),
        "mode": "paper",
    })
    ex.get_current_price = AsyncMock(return_value=fill_price)
    return ex


def make_position_obj(entry=100.0, amount=1.0, symbol="BTC/USDT", stop_loss=88.0):
    pos = Position(
        symbol=symbol,
        entry_price=entry,
        amount=amount,
        amount_usd=entry * amount,
        stop_loss=stop_loss,
        take_profit_1=entry * 1.40,
        take_profit_2=entry * 2.00,
        setup_type="breakout",
    )
    return pos


def make_pm(fill_price=100.0) -> PositionManager:
    ex = make_mock_execution(fill_price=fill_price)
    return PositionManager(
        execution=ex,
        trailing_activate_pct=15.0,
        trailing_distance_pct=8.0,
        tier1_exit_pct=0.25,
        tier2_exit_pct=0.25,
        time_exit_hours=4.0,
        stop_loss_pct=-18.0,
    )


def test_position_object_has_required_fields():
    pos = make_position_obj()
    d = pos.to_dict()
    for field in ("id", "symbol", "entry_price", "amount_usd", "stop_loss", "take_profit_1", "tier1_done", "status"):
        assert field in d


def test_stop_loss_below_entry():
    pos = make_position_obj(entry=100.0, stop_loss=88.0)
    assert pos.stop_loss < pos.entry_price


def test_take_profit_above_entry():
    pos = make_position_obj(entry=100.0)
    assert pos.take_profit_1 > pos.entry_price
    assert pos.take_profit_2 > pos.take_profit_1


def test_current_pnl_pct():
    pos = make_position_obj(entry=100.0)
    assert abs(pos.current_pnl_pct(110.0) - 10.0) < 0.01
    assert pos.current_pnl_pct(90.0) < 0


def test_open_count_and_symbols():
    pm = make_pm()
    pos1 = make_position_obj(symbol="BTC/USDT")
    pos2 = make_position_obj(symbol="ETH/USDT")
    pm._positions[pos1.id] = pos1
    pm._positions[pos2.id] = pos2
    assert pm.open_count == 2
    assert "BTC/USDT" in pm.get_open_symbols()
    assert "ETH/USDT" in pm.get_open_symbols()


def test_get_total_exposure():
    pm = make_pm()
    pos = make_position_obj(entry=100.0, amount=2.0)
    pm._positions[pos.id] = pos
    assert pm.get_total_exposure_usd() == 200.0


@pytest.mark.asyncio
async def test_update_all_triggers_stop_loss():
    ex = make_mock_execution(fill_price=85.0)
    pm = PositionManager(execution=ex, stop_loss_pct=-18.0, time_exit_hours=4.0)
    pos = make_position_obj(entry=100.0, stop_loss=88.0)
    pm._positions[pos.id] = pos

    exits = await pm.update_all()
    assert len(exits) == 1 or pos.status == "closed"


@pytest.mark.asyncio
async def test_open_position_paper_mode():
    ex = make_mock_execution(fill_price=100.0, fill_amount=1.0)
    pm = PositionManager(execution=ex)
    setup = {
        "symbol": "BTC/USDT",
        "price": 100.0,
        "setup_type": "breakout",
        "entry_zone": {"stop_loss": 88.0, "rr_ratio": 3.0},
    }
    pos = await pm.open_position(setup=setup, amount_usd=100.0)
    assert pos is not None
    assert pos.symbol == "BTC/USDT"
    assert pos.entry_price == 100.0


@pytest.mark.asyncio
async def test_momentum_review_exits_stale_trade_after_15m():
    ex = make_mock_execution(fill_price=100.1, fill_amount=1.0)
    pm = PositionManager(execution=ex, momentum_recheck_interval_minutes=5)
    pos = make_position_obj(entry=100.0, stop_loss=80.0)
    pos.opened_at = int(time.time()) - 16 * 60
    pos.highest_price = 100.7
    pm._positions[pos.id] = pos

    exits = await pm.update_all()

    assert ex.exit_position.await_count == 1
    assert exits[0]["close_reason"] == "momentum_died_15m"


@pytest.mark.asyncio
async def test_momentum_review_keeps_runner_with_real_run_up():
    ex = make_mock_execution(fill_price=100.8, fill_amount=1.0)
    pm = PositionManager(execution=ex, momentum_recheck_interval_minutes=5)
    pos = make_position_obj(entry=100.0, stop_loss=80.0)
    pos.opened_at = int(time.time()) - 16 * 60
    pos.highest_price = 101.8
    pm._positions[pos.id] = pos

    exits = await pm.update_all()

    assert exits == []
    ex.exit_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_regime_time_exit_overrides_base_time_exit():
    ex = make_mock_execution(fill_price=100.0, fill_amount=1.0)
    pm = PositionManager(execution=ex, time_exit_hours=4.0)
    pos = make_position_obj(entry=100.0, stop_loss=80.0)
    pos.opened_at = int(time.time()) - int(1.1 * 3600)
    pos.tier1_done = True
    pm._positions[pos.id] = pos

    exits = await pm.update_all(regime_params={"time_exit_hours": 1.0})

    assert ex.exit_position.await_count == 1
    assert exits[0]["close_reason"] == "time_exit"
