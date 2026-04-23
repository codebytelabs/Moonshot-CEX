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
    ex.enter_position = AsyncMock(
        return_value={
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
        }
    )
    ex.exit_position = AsyncMock(
        return_value={
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
        }
    )
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
    for field in (
        "id",
        "symbol",
        "entry_price",
        "amount_usd",
        "stop_loss",
        "take_profit_1",
        "tier1_done",
        "status",
    ):
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
async def test_momentum_faded_after_significant_peak_giveback():
    """v8.0: early momentum kills were 0% WR; only `momentum_faded` (peak ≥3%,
    ≥60%+ giveback from peak, current pnl <0.5% after 30min+ hold) remains as
    the justified momentum exit. Entry 100 → peak 104 (+4%) → current 100.4
    (+0.4%, 90% giveback from peak).
    """
    ex = make_mock_execution(fill_price=100.4, fill_amount=1.0)
    pm = PositionManager(execution=ex, momentum_recheck_interval_minutes=5)
    pos = make_position_obj(entry=100.0, stop_loss=80.0)
    pos.opened_at = int(time.time()) - 31 * 60  # >30 min hold
    pos.highest_price = 104.0  # +4% peak
    pm._positions[pos.id] = pos

    exits = await pm.update_all()

    assert ex.exit_position.await_count == 1
    assert exits[0]["close_reason"] == "momentum_faded"


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
async def test_regime_time_exit_max_overrides_base_time_exit():
    """v8.0: the primary `time_exit` (losing-trade killer at the regime hours)
    was removed — data showed it killed winners before they trailed. Only the
    safety ceiling `time_exit_max` at 2× the regime time remains. Regime params
    must still drive this ceiling. Hold 2.1h with regime time_exit_hours=1.0
    (=> max 2.0h) must trigger `time_exit_max`.
    """
    ex = make_mock_execution(fill_price=100.0, fill_amount=1.0)
    pm = PositionManager(execution=ex, time_exit_hours=4.0)
    pos = make_position_obj(entry=100.0, stop_loss=80.0)
    pos.opened_at = int(time.time()) - int(2.1 * 3600)
    pos.tier1_done = True
    pm._positions[pos.id] = pos

    exits = await pm.update_all(regime_params={"time_exit_hours": 1.0})

    assert ex.exit_position.await_count == 1
    assert exits[0]["close_reason"] == "time_exit_max"


# ── scale_position tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scale_up_buys_only_delta():
    """When target > current value by >10%, enter_position is called for the delta only."""
    fill_price = 100.0
    fill_amount = 2.0  # will be the delta buy
    ex = make_mock_execution(fill_price=fill_price, fill_amount=fill_amount)
    # Build PM directly with this ex so assertions target the right mock
    pm = PositionManager(execution=ex, trailing_activate_pct=15.0, stop_loss_pct=-18.0)

    # Existing position: 3 units @ $100 = $300 current value
    pos = make_position_obj(entry=100.0, amount=3.0)
    pm._positions[pos.id] = pos

    # Target: $500 → delta = $200 → well outside 10% tolerance
    result = await pm.scale_position(
        pos, target_usd=500.0, current_price=100.0, tolerance_pct=10.0
    )

    assert result == "scaled_up"
    ex.enter_position.assert_awaited_once()
    ex.exit_position.assert_not_awaited()
    # Amount should have grown
    assert pos.amount > 3.0


@pytest.mark.asyncio
async def test_scale_hold_within_tolerance():
    """When target is within ±10% of current value, no trade is placed."""
    ex = make_mock_execution(fill_price=100.0)
    pm = PositionManager(execution=ex, trailing_activate_pct=15.0, stop_loss_pct=-18.0)

    # Existing: 3 units @ $100 = $300.  Target $305 is ~1.7% away → hold.
    pos = make_position_obj(entry=100.0, amount=3.0)
    pm._positions[pos.id] = pos

    result = await pm.scale_position(
        pos, target_usd=305.0, current_price=100.0, tolerance_pct=10.0
    )

    assert result == "hold"
    ex.enter_position.assert_not_awaited()
    ex.exit_position.assert_not_awaited()
    # Amount unchanged
    assert pos.amount == 3.0


@pytest.mark.asyncio
async def test_scale_down_is_disabled_by_design():
    """scale_down was disabled in commit 50389fe after real-trade data showed
    repeated scale-downs turning $622 positions into dust (e.g. BNB: 4 chained
    scale_downs). Scale requests below current value must return 'hold' without
    touching execution so live positions are never unwound by size drift alone.
    """
    fill_price = 100.0
    sell_amount = 2.0
    ex = make_mock_execution(fill_price=fill_price, fill_amount=sell_amount)
    pm = PositionManager(execution=ex, trailing_activate_pct=15.0, stop_loss_pct=-18.0)

    pos = make_position_obj(entry=100.0, amount=5.0)
    pm._positions[pos.id] = pos

    result = await pm.scale_position(
        pos, target_usd=200.0, current_price=100.0, tolerance_pct=10.0
    )

    # scale_down path is explicitly disabled — hold without trading.
    assert result == "hold"
    ex.exit_position.assert_not_awaited()
    ex.enter_position.assert_not_awaited()
    assert pos.amount == 5.0
