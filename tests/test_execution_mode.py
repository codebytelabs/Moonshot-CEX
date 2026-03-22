"""
Tests for ExecutionCore: verifies paper mode simulates fills while
demo/live mode calls real exchange methods.
"""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.execution_core import ExecutionCore


def _make_mock_exchange(fill_price: float = 1.0, fill_amount: float = 100.0):
    ex = MagicMock()
    ex.name = "gateio"
    ex.cost_to_amount = MagicMock(return_value=fill_amount)
    ex.amount_to_precision = MagicMock(side_effect=lambda _symbol, amount: float(amount))
    ex.price_to_precision = MagicMock(side_effect=lambda _symbol, price: float(price))
    order_response = {"id": "test-order-123", "status": "closed"}
    fill_response = {
        "status": "closed",
        "average": fill_price,
        "filled": fill_amount,
        "fee": {"cost": 0.1, "currency": "USDT"},
    }
    ex.create_market_buy = AsyncMock(return_value=order_response)
    ex.create_market_sell = AsyncMock(return_value=order_response)
    ex.create_limit_sell = AsyncMock(return_value=order_response)
    ex.fetch_order = AsyncMock(return_value=fill_response)
    ex.fetch_balance = AsyncMock(return_value={
        "SOL": {"free": fill_amount},
        "BTC": {"free": fill_amount},
        "ETH": {"free": fill_amount},
        "BNB": {"free": fill_amount},
        "XRP": {"free": fill_amount},
    })
    ex.fetch_order_book = AsyncMock(return_value={
        "bids": [[fill_price * 0.999, fill_amount]],
        "asks": [[fill_price * 1.001, fill_amount]],
    })
    ex.cancel_order = AsyncMock(return_value={"id": "test-order-123", "status": "canceled"})
    return ex


@pytest.mark.asyncio
async def test_paper_mode_does_not_call_exchange_on_entry():
    mock_ex = _make_mock_exchange()
    core = ExecutionCore(exchange=mock_ex, exchange_mode="paper")

    result = await core.enter_position(
        symbol="BTC/USDT", side="buy", amount_usd=100.0, price=50000.0
    )

    mock_ex.create_market_buy.assert_not_called()
    mock_ex.create_market_sell.assert_not_called()
    assert result["mode"] == "paper"
    assert result["order_id"].startswith("paper_")


@pytest.mark.asyncio
async def test_paper_mode_does_not_call_exchange_on_exit():
    mock_ex = _make_mock_exchange(fill_price=50000.0)
    core = ExecutionCore(exchange=mock_ex, exchange_mode="paper")

    result = await core.exit_position(
        symbol="BTC/USDT", amount=0.002, price=50000.0, reason="stop_loss"
    )

    mock_ex.create_market_buy.assert_not_called()
    mock_ex.create_market_sell.assert_not_called()
    assert result["mode"] == "paper"
    assert result["order_id"].startswith("paper_")


@pytest.mark.asyncio
async def test_demo_mode_calls_exchange_on_entry():
    mock_ex = _make_mock_exchange(fill_price=1.0, fill_amount=100.0)
    core = ExecutionCore(exchange=mock_ex, exchange_mode="demo")

    result = await core.enter_position(
        symbol="ETH/USDT", side="buy", amount_usd=100.0, price=1.0
    )

    mock_ex.create_market_buy.assert_called_once()
    assert result["mode"] == "demo"
    assert result["order_id"] == "test-order-123"


@pytest.mark.asyncio
async def test_demo_mode_calls_exchange_on_exit():
    mock_ex = _make_mock_exchange(fill_price=1.0, fill_amount=10.0)
    core = ExecutionCore(exchange=mock_ex, exchange_mode="demo")

    result = await core.exit_position(
        symbol="SOL/USDT", amount=10.0, price=1.0, reason="trailing_stop"
    )

    mock_ex.create_limit_sell.assert_called_once()
    mock_ex.create_market_sell.assert_not_called()
    assert result["mode"] == "demo"
    assert result["order_id"] == "test-order-123"


@pytest.mark.asyncio
async def test_live_mode_calls_exchange_on_entry():
    mock_ex = _make_mock_exchange(fill_price=100.0, fill_amount=1.0)
    core = ExecutionCore(exchange=mock_ex, exchange_mode="live")

    result = await core.enter_position(
        symbol="BNB/USDT", side="buy", amount_usd=100.0, price=100.0
    )

    mock_ex.create_market_buy.assert_called_once()
    assert result["mode"] == "live"


@pytest.mark.asyncio
async def test_paper_fill_applies_slippage():
    mock_ex = _make_mock_exchange()
    core = ExecutionCore(exchange=mock_ex, exchange_mode="paper")

    result = await core.enter_position(
        symbol="BTC/USDT", side="buy", amount_usd=1000.0, price=50000.0
    )

    assert result["filled_price"] > 50000.0
    assert result["fee_usd"] == pytest.approx(1000.0 * 0.001, rel=1e-3)


@pytest.mark.asyncio
async def test_paper_mode_exit_returns_sell_side():
    mock_ex = _make_mock_exchange()
    core = ExecutionCore(exchange=mock_ex, exchange_mode="paper")

    result = await core.exit_position(
        symbol="BTC/USDT", amount=0.01, price=50000.0, reason="take_profit_1"
    )

    assert result["side"] == "sell"
    assert result["mode"] == "paper"


@pytest.mark.asyncio
async def test_demo_mode_exit_reprices_limit_sell_until_fill():
    mock_ex = _make_mock_exchange(fill_price=1.0, fill_amount=10.0)
    mock_ex.fetch_order = AsyncMock(side_effect=[
        {"status": "open", "filled": 0.0, "fee": {"cost": 0.0, "currency": "USDT"}},
        {"status": "open", "filled": 0.0, "fee": {"cost": 0.0, "currency": "USDT"}},
        {"status": "open", "filled": 0.0, "fee": {"cost": 0.0, "currency": "USDT"}},
        {"status": "closed", "average": 1.0, "filled": 10.0, "fee": {"cost": 0.1, "currency": "USDT"}},
    ])
    core = ExecutionCore(exchange=mock_ex, exchange_mode="demo", max_retries=3, exit_limit_poll_seconds=1)

    result = await core.exit_position(
        symbol="SOL/USDT", amount=10.0, price=1.0, reason="momentum_died_15m"
    )

    assert mock_ex.create_limit_sell.call_count == 2
    mock_ex.cancel_order.assert_called_once()
    assert result["filled_amount"] == 10.0


@pytest.mark.asyncio
async def test_demo_mode_entry_retries_on_exchange_failure():
    mock_ex = _make_mock_exchange(fill_price=1.0, fill_amount=100.0)
    mock_ex.create_market_buy = AsyncMock(
        side_effect=[Exception("network error"), {"id": "retry-order", "status": "closed"}]
    )
    mock_ex.fetch_order = AsyncMock(return_value={
        "status": "closed",
        "average": 1.0,
        "filled": 100.0,
        "fee": {"cost": 0.05, "currency": "USDT"},
    })
    core = ExecutionCore(exchange=mock_ex, exchange_mode="demo", max_retries=3)

    result = await core.enter_position(
        symbol="XRP/USDT", side="buy", amount_usd=100.0, price=1.0
    )

    assert mock_ex.create_market_buy.call_count == 2
    assert result["order_id"] == "retry-order"


@pytest.mark.asyncio
async def test_paper_mode_consecutive_orders_increment_counter():
    mock_ex = _make_mock_exchange()
    core = ExecutionCore(exchange=mock_ex, exchange_mode="paper")

    r1 = await core.enter_position("BTC/USDT", "buy", 100.0, 50000.0)
    r2 = await core.enter_position("ETH/USDT", "buy", 100.0, 3000.0)

    assert r1["order_id"] != r2["order_id"]
    assert r1["order_id"] == "paper_1"
    assert r2["order_id"] == "paper_2"
