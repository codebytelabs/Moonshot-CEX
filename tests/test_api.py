"""Integration tests for backend API endpoints."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_BASE_STATE = {
    "running": False,
    "paused": False,
    "emergency_stop": False,
    "cycle_count": 0,
    "mode": "paper",
    "regime": "sideways",
    "regime_params": {},
    "current_equity": 1000.0,
    "peak_equity": 1000.0,
    "day_pnl_usd": 0.0,
    "day_pnl_pct": 0.0,
    "total_pnl_usd": 0.0,
    "last_cycle_at": 0,
    "last_watcher_candidates": [],
    "last_setups": [],
    "last_decisions": [],
    "recent_events": [],
    "start_time": 0.0,
    "bigbrother_mode": "normal",
}


def _make_mock_cfg():
    cfg = MagicMock()
    cfg.exchange_name = "gateio"
    cfg.exchange_mode = "paper"
    cfg.max_positions = 5
    cfg.max_portfolio_exposure_pct = 0.8
    cfg.stop_loss_pct = -0.12
    cfg.trailing_stop_activate_pct = 0.15
    cfg.trailing_stop_distance_pct = 0.08
    cfg.analyzer_top_n = 5
    cfg.cycle_interval_seconds = 60
    cfg.context_agent_enabled = False
    cfg.pyramid_enabled = False
    cfg.initial_equity_usd = 1000.0
    return cfg


def test_health_endpoint():
    with (
        patch("backend.server.STATE", dict(_BASE_STATE)),
        patch("backend.server.cfg", _make_mock_cfg()),
        patch("backend.server._mongo_client", None),
        patch("backend.server._db", None),
        patch("backend.server._bigbrother", None),
        patch("backend.server._position_manager", None),
        patch("backend.server._risk_manager", None),
    ):
        from fastapi.testclient import TestClient
        from backend.server import app
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "running" in data
        assert "uptime" in data


def test_swarm_status_endpoint():
    state = dict(_BASE_STATE)
    state["cycle_count"] = 42
    mock_pm = MagicMock()
    mock_pm.open_count = 2

    with (
        patch("backend.server.STATE", state),
        patch("backend.server.cfg", _make_mock_cfg()),
        patch("backend.server._bigbrother", None),
        patch("backend.server._position_manager", mock_pm),
        patch("backend.server._risk_manager", None),
        patch("backend.server._mongo_client", None),
        patch("backend.server._db", None),
    ):
        from fastapi.testclient import TestClient
        from backend.server import app
        client = TestClient(app)
        resp = client.get("/api/swarm/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data
        assert "cycle_count" in data
        assert data["cycle_count"] == 42


def test_portfolio_endpoint_structure():
    mock_pm = MagicMock()
    mock_pm.get_open_positions.return_value = []
    mock_pm.get_total_exposure_usd.return_value = 0.0

    mock_rm = MagicMock()
    mock_rm.check_portfolio_health.return_value = {"ok": True}

    with (
        patch("backend.server.STATE", dict(_BASE_STATE)),
        patch("backend.server.cfg", _make_mock_cfg()),
        patch("backend.server._position_manager", mock_pm),
        patch("backend.server._risk_manager", mock_rm),
        patch("backend.server._mongo_client", None),
        patch("backend.server._db", None),
    ):
        from fastapi.testclient import TestClient
        from backend.server import app
        client = TestClient(app)
        resp = client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert "open_positions" in data
        assert "open_count" in data
        assert "equity" in data
        assert data["equity"] == 1000.0


def test_portfolio_endpoint_uses_exchange_snapshot_in_demo_mode():
    cfg = _make_mock_cfg()
    cfg.exchange_mode = "demo"
    mock_rm = MagicMock()
    mock_rm.check_portfolio_health.return_value = {"ok": True}
    snapshot = {
        "source": "exchange",
        "equity": 4321.0,
        "cash_usd": 321.0,
        "open_positions": [{"id": "exchange-btc-usdt", "symbol": "BTC/USDT"}],
        "open_count": 1,
        "exposure_usd": 4000.0,
    }

    with (
        patch("backend.server.STATE", dict(_BASE_STATE)),
        patch("backend.server.cfg", cfg),
        patch("backend.server._risk_manager", mock_rm),
        patch("backend.server._position_manager", MagicMock()),
        patch("backend.server._mongo_client", None),
        patch("backend.server._db", None),
        patch("backend.server._get_exchange_account_snapshot", AsyncMock(return_value=snapshot)),
    ):
        from fastapi.testclient import TestClient
        from backend.server import app
        client = TestClient(app)
        resp = client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "exchange"
        assert data["equity"] == 4321.0
        assert data["cash_usd"] == 321.0
        assert data["open_count"] == 1
        assert data["open_positions"][0]["symbol"] == "BTC/USDT"


def test_autopilot_endpoint():
    with (
        patch("backend.server.STATE", dict(_BASE_STATE)),
        patch("backend.server.cfg", _make_mock_cfg()),
        patch("backend.server._mongo_client", None),
        patch("backend.server._db", None),
    ):
        from fastapi.testclient import TestClient
        from backend.server import app
        client = TestClient(app)
        resp = client.get("/api/swarm/autopilot")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "paper"
        assert data["paper"] is True
        assert data["live"] is False


def test_feed_endpoint():
    state = dict(_BASE_STATE)
    state["last_watcher_candidates"] = [{"symbol": "BTC/USDT", "score": 80}]
    state["recent_events"] = [{"type": "regime_change", "regime": "bull"}]

    with (
        patch("backend.server.STATE", state),
        patch("backend.server.cfg", _make_mock_cfg()),
        patch("backend.server._mongo_client", None),
        patch("backend.server._db", None),
    ):
        from fastapi.testclient import TestClient
        from backend.server import app
        client = TestClient(app)
        resp = client.get("/api/feed")
        assert resp.status_code == 200
        data = resp.json()
        assert "candidates" in data
        assert "events" in data
        assert len(data["candidates"]) == 1


def test_trades_endpoint_uses_exchange_history_in_demo_mode():
    cfg = _make_mock_cfg()
    cfg.exchange_mode = "demo"
    exchange_trades = [{"id": "t1", "symbol": "ETH/USDT", "source": "exchange"}]

    with (
        patch("backend.server.STATE", dict(_BASE_STATE)),
        patch("backend.server.cfg", cfg),
        patch("backend.server._mongo_client", None),
        patch("backend.server._db", None),
        patch("backend.server._get_exchange_trade_history", AsyncMock(return_value=exchange_trades)),
    ):
        from fastapi.testclient import TestClient
        from backend.server import app
        client = TestClient(app)
        resp = client.get("/api/trades?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "exchange"
        assert data["trades"] == exchange_trades


def test_positions_endpoint_uses_exchange_snapshot_in_demo_mode():
    cfg = _make_mock_cfg()
    cfg.exchange_mode = "demo"
    snapshot = {
        "source": "exchange",
        "open_positions": [{"id": "exchange-kas-usdt", "symbol": "KAS/USDT"}],
        "open_count": 1,
        "equity": 1000.0,
        "cash_usd": 10.0,
        "exposure_usd": 990.0,
    }

    with (
        patch("backend.server.STATE", dict(_BASE_STATE)),
        patch("backend.server.cfg", cfg),
        patch("backend.server._mongo_client", None),
        patch("backend.server._db", None),
        patch("backend.server._get_exchange_account_snapshot", AsyncMock(return_value=snapshot)),
    ):
        from fastapi.testclient import TestClient
        from backend.server import app
        client = TestClient(app)
        resp = client.get("/api/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "exchange"
        assert data["positions"][0]["symbol"] == "KAS/USDT"


def test_regime_endpoint():
    state = dict(_BASE_STATE)
    state["regime"] = "bull"
    state["regime_params"] = {"stop_loss_pct": -0.12}

    with (
        patch("backend.server.STATE", state),
        patch("backend.server.cfg", _make_mock_cfg()),
        patch("backend.server._mongo_client", None),
        patch("backend.server._db", None),
    ):
        from fastapi.testclient import TestClient
        from backend.server import app
        client = TestClient(app)
        resp = client.get("/api/regime")
        assert resp.status_code == 200
        data = resp.json()
        assert data["regime"] == "bull"
        assert "params" in data
