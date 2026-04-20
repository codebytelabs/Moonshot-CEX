import asyncio
import json
import os
import subprocess
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.chiron import ChironCoach
from src.risk_manager import RiskManager
from src.strategies.regime_engine import RegimeEngine


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


def test_chiron_builds_defensive_runtime_overrides():
    rm = make_rm()
    regime_engine = RegimeEngine(exchange=MagicMock())
    coach = ChironCoach(
        db=None,
        risk_manager=rm,
        regime_engine=regime_engine,
        llm_enabled=False,
        min_trades_per_bucket=5,
        min_total_trades=10,
        auto_apply_low_risk=True,
    )
    snapshot = {
        "by_setup": {
            "ema_trend_follow": {
                "trades": 6,
                "smoothed_win_rate": 0.22,
                "pnl_usd": -180.0,
                "profit_factor": 0.35,
            }
        },
        "by_regime_strategy": {
            "bull|ema_trend": {
                "trades": 6,
                "smoothed_win_rate": 0.24,
                "pnl_usd": -150.0,
                "profit_factor": 0.40,
            }
        },
        "overall": {
            "trades": 12,
            "smoothed_win_rate": 0.38,
            "pnl_usd": -260.0,
            "profit_factor": 0.55,
        },
    }

    proposals = coach.propose(snapshot, current_min_score=40.0, current_bayesian_threshold=0.55)
    applied = coach.select_applied_overrides(proposals)

    assert any(p.kind == "setup_size_mult" for p in proposals)
    assert any(p.kind == "setup_pause" for p in proposals)
    assert any(p.kind == "regime_weight_mult" for p in proposals)
    assert applied["setup_size_mult"]["ema_trend_follow"] < 1.0
    assert applied["setup_pause_minutes"]["ema_trend_follow"] == coach.interval_hours * 60
    assert applied["regime_weight_mult"]["bull"]["ema_trend"] < 1.0


def test_chiron_keeps_min_score_and_threshold_as_suggestions():
    coach = ChironCoach(
        db=None,
        llm_enabled=False,
        min_trades_per_bucket=5,
        min_total_trades=10,
        auto_apply_low_risk=True,
    )
    snapshot = {
        "by_setup": {},
        "by_regime_strategy": {},
        "overall": {
            "trades": 12,
            "smoothed_win_rate": 0.39,
            "pnl_usd": -120.0,
            "profit_factor": 0.70,
        },
    }

    proposals = coach.propose(snapshot, current_min_score=40.0, current_bayesian_threshold=0.55)
    kinds = {p.kind: p for p in proposals}
    applied = coach.select_applied_overrides(proposals)

    assert kinds["min_score"].action == "suggest"
    assert kinds["bayesian_threshold"].action == "suggest"
    assert applied == {}


def test_risk_manager_runtime_overrides_replace_static_setup_multiplier_and_pause_entries():
    rm = make_rm()
    base = _size(rm, setup_type="ema_trend_follow")

    rm.set_runtime_setup_overrides(
        size_mult={"ema_trend_follow": 0.8},
        pause_minutes={"ema_trend_follow": 5},
    )
    boosted = _size(rm, setup_type="ema_trend_follow")
    allowed, reason = rm.can_open_position(
        current_equity=10_000.0,
        open_count=0,
        current_exposure_usd=0.0,
        symbol="BTC/USDT",
        open_symbols=set(),
        setup_type="ema_trend_follow",
    )

    assert boosted > base
    assert rm.get_effective_setup_size_multiplier("ema_trend_follow") == 0.8
    assert not allowed
    assert "setup_circuit_breaker:ema_trend_follow" in reason


def test_regime_engine_runtime_weight_override_changes_effective_weights():
    engine = RegimeEngine(exchange=MagicMock())
    base = engine.get_effective_weights("bull")

    engine.set_runtime_weight_overrides({"bull": {"ema_trend": 0.5}})
    updated = engine.get_effective_weights("bull")

    assert updated["ema_trend"] < base["ema_trend"]
    assert updated["vwap_momentum"] == base["vwap_momentum"]


def test_chiron_promote_persists_stable_low_risk_overrides(tmp_path):
    promotion_path = tmp_path / "config" / "chiron_promotions.json"
    coach = ChironCoach(
        db=None,
        llm_enabled=False,
        promotion_enabled=True,
        promotion_file_path=str(promotion_path),
        promotion_min_occurrences=2,
        promotion_lookback_runs=4,
        repo_path=str(tmp_path),
    )
    repeated_setup = {
        "kind": "setup_size_mult",
        "key": "setup_size_mult:ema_trend_follow",
        "setup_type": "ema_trend_follow",
        "proposed_value": 0.85,
        "risk_tier": "low",
        "action": "auto_apply",
    }
    repeated_regime = {
        "kind": "regime_weight_mult",
        "key": "regime_weight_mult:bull:ema_trend",
        "regime": "bull",
        "strategy": "ema_trend",
        "proposed_value": 0.8,
        "risk_tier": "low",
        "action": "auto_apply",
    }
    recent_runs = [
        {"proposals": [repeated_setup, repeated_regime]},
        {"proposals": [dict(repeated_setup), dict(repeated_regime)]},
    ]

    result = asyncio.run(coach.promote(recent_runs=recent_runs))
    persisted = json.loads(promotion_path.read_text())

    assert result["status"] == "updated"
    assert persisted["promotions"]["setup_size_mult"]["ema_trend_follow"] == 0.85
    assert persisted["promotions"]["regime_weight_mult"]["bull"]["ema_trend"] == 0.8
    assert "setup_size_mult:ema_trend_follow" in result["promoted_keys"]


def test_chiron_commit_promotions_commits_tracked_artifact(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo_path)], check=True, capture_output=True)
    promotion_path = repo_path / "config" / "chiron_promotions.json"
    promotion_path.parent.mkdir(parents=True, exist_ok=True)
    promotion_path.write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": 123,
                "promotions": {"setup_size_mult": {"ema_trend_follow": 0.85}, "regime_weight_mult": {}},
                "metadata": {"promoted_keys": ["setup_size_mult:ema_trend_follow"], "source": "chiron"},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    coach = ChironCoach(
        db=None,
        llm_enabled=False,
        promotion_enabled=True,
        promotion_file_path=str(promotion_path),
        repo_path=str(repo_path),
    )

    result = coach.commit_promotions()
    log = subprocess.run(
        ["git", "-C", str(repo_path), "log", "--oneline", "-1"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result["status"] == "committed"
    assert "chiron: promote stable runtime tuning" in log.stdout
