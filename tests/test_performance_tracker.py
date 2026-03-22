"""Unit tests for src/performance_tracker.py."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.performance_tracker import PerformanceTracker


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_trade(pnl: float, r: float = 1.0, offset_secs: int = 0) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "pnl": pnl,
        "r_multiple": r,
        "status": "closed",
        "saved_at": (now - timedelta(seconds=offset_secs)).timestamp(),
    }


def _mock_db_with_trades(trades: list) -> MagicMock:
    """Build a mock MongoDB `_db` whose trades.find returns the given list."""
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=trades)

    mock_collection = MagicMock()
    mock_collection.find = MagicMock(return_value=mock_cursor)
    mock_collection.count_documents = AsyncMock(return_value=0)

    mock_db = MagicMock()
    mock_db.trades = mock_collection
    mock_db.positions = mock_collection
    return mock_db


# ── _rolling ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rolling_empty():
    tracker = PerformanceTracker(db=None)
    result = await tracker._rolling(datetime.now(timezone.utc), 7)
    assert result["total_trades"] == 0
    assert result["win_rate"] == 0.0
    assert result["profit_factor"] == 0.0


@pytest.mark.asyncio
async def test_rolling_win_rate():
    trades = [_make_trade(100.0), _make_trade(50.0), _make_trade(-30.0), _make_trade(-10.0)]
    db = _mock_db_with_trades(trades)
    tracker = PerformanceTracker(db=db)

    result = await tracker._rolling(datetime.now(timezone.utc), 7)

    assert result["total_trades"] == 4
    assert result["win_rate"] == 50.0
    assert result["total_pnl"] == pytest.approx(110.0)


@pytest.mark.asyncio
async def test_rolling_profit_factor():
    trades = [_make_trade(200.0), _make_trade(100.0), _make_trade(-100.0)]
    db = _mock_db_with_trades(trades)
    tracker = PerformanceTracker(db=db)

    result = await tracker._rolling(datetime.now(timezone.utc), 7)

    assert result["profit_factor"] == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_rolling_all_wins():
    trades = [_make_trade(50.0), _make_trade(75.0), _make_trade(25.0)]
    db = _mock_db_with_trades(trades)
    tracker = PerformanceTracker(db=db)

    result = await tracker._rolling(datetime.now(timezone.utc), 7)

    assert result["win_rate"] == 100.0
    assert result["profit_factor"] == 0.0


@pytest.mark.asyncio
async def test_rolling_all_losses():
    trades = [_make_trade(-50.0), _make_trade(-75.0)]
    db = _mock_db_with_trades(trades)
    tracker = PerformanceTracker(db=db)

    result = await tracker._rolling(datetime.now(timezone.utc), 7)

    assert result["win_rate"] == 0.0
    assert result["total_pnl"] == pytest.approx(-125.0)


# ── _drawdown_from_curve ──────────────────────────────────────────────────────

def test_drawdown_empty():
    assert PerformanceTracker._drawdown_from_curve([]) == 0.0


def test_drawdown_no_loss():
    curve = [
        {"ts": "t1", "equity": 10000},
        {"ts": "t2", "equity": 10500},
        {"ts": "t3", "equity": 11000},
    ]
    assert PerformanceTracker._drawdown_from_curve(curve) == 0.0


def test_drawdown_calculated():
    curve = [
        {"ts": "t1", "equity": 10000},
        {"ts": "t2", "equity": 11000},
        {"ts": "t3", "equity": 9350},
    ]
    dd = PerformanceTracker._drawdown_from_curve(curve)
    assert dd == pytest.approx(15.0, abs=0.1)


def test_drawdown_multiple_peaks():
    curve = [
        {"ts": "t1", "equity": 10000},
        {"ts": "t2", "equity": 12000},
        {"ts": "t3", "equity": 10200},
        {"ts": "t4", "equity": 13000},
        {"ts": "t5", "equity": 9750},
    ]
    dd = PerformanceTracker._drawdown_from_curve(curve)
    assert dd == pytest.approx(25.0, abs=0.1)


# ── _check_alerts ─────────────────────────────────────────────────────────────

def test_no_alerts_healthy():
    tracker = PerformanceTracker()
    metrics = {"total_trades": 20, "win_rate": 55.0, "profit_factor": 1.8,
                "avg_r_multiple": 1.2, "daily_pnl": 10.0, "total_pnl": 100.0, "window_days": 7}
    alerts = tracker._check_alerts(metrics, drawdown=5.0)
    assert alerts == []


def test_alert_win_rate_below_threshold():
    tracker = PerformanceTracker()
    metrics = {"total_trades": 15, "win_rate": 35.0, "profit_factor": 0.9,
                "avg_r_multiple": 0.8, "daily_pnl": -5.0, "total_pnl": -50.0, "window_days": 7}
    alerts = tracker._check_alerts(metrics, drawdown=5.0)
    assert any(a["type"] == "win_rate_degradation" for a in alerts)


def test_alert_drawdown_exceeded():
    tracker = PerformanceTracker()
    metrics = {"total_trades": 15, "win_rate": 55.0, "profit_factor": 1.5,
                "avg_r_multiple": 1.0, "daily_pnl": 5.0, "total_pnl": 50.0, "window_days": 7}
    alerts = tracker._check_alerts(metrics, drawdown=20.0)
    assert any(a["type"] == "drawdown_exceeded" for a in alerts)
    assert alerts[0]["severity"] == "critical"


def test_no_alert_below_min_trades_threshold():
    tracker = PerformanceTracker()
    metrics = {"total_trades": 5, "win_rate": 30.0, "profit_factor": 0.5,
                "avg_r_multiple": 0.5, "daily_pnl": -10.0, "total_pnl": -100.0, "window_days": 7}
    alerts = tracker._check_alerts(metrics, drawdown=5.0)
    assert not any(a["type"] == "win_rate_degradation" for a in alerts)


# ── get_current_metrics ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_current_metrics_no_db():
    tracker = PerformanceTracker(db=None)
    result = await tracker.get_current_metrics()
    assert "rolling_7day" in result
    assert "rolling_30day" in result
    assert "all_time" in result
    assert "equity_curve" in result
    assert "alerts" in result
    assert result["rolling_7day"]["total_trades"] == 0


@pytest.mark.asyncio
async def test_get_current_metrics_with_trades():
    trades = [
        _make_trade(150.0, r=2.0),
        _make_trade(80.0, r=1.5),
        _make_trade(-40.0, r=-0.8),
    ]
    db = _mock_db_with_trades(trades)
    tracker = PerformanceTracker(db=db)
    result = await tracker.get_current_metrics()

    r7 = result["rolling_7day"]
    assert r7["total_trades"] == 3
    assert r7["win_rate"] == pytest.approx(66.67, abs=0.1)
    assert r7["total_pnl"] == pytest.approx(190.0)
