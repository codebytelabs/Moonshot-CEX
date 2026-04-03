"""Unit tests for BayesianDecisionEngine."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.bayesian_engine import BayesianDecisionEngine, SETUP_PRIORS, MODE_THRESHOLDS


def make_setup(ta_score=70, setup_type="breakout", sentiment="bullish", risks=None, vol_ratio=1.5, rr_ratio=3.0):
    return {
        "symbol": "BTC/USDT",
        "ta_score": ta_score,
        "setup_type": setup_type,
        "vol_ratio": vol_ratio,
        "entry_zone": {"rr_ratio": rr_ratio},
        "context": {
            "sentiment": sentiment,
            "confidence": 0.75,
            "driver_type": "narrative",
            "catalysts": ["ETF inflows"],
            "risks": risks or [],
        },
    }


def test_decide_returns_required_fields():
    engine = BayesianDecisionEngine(mode="normal")
    result = engine.decide(make_setup())
    for field in ("action", "posterior", "threshold", "prior", "setup_type", "reasoning"):
        assert field in result


def test_action_values_are_valid():
    engine = BayesianDecisionEngine(mode="normal")
    result = engine.decide(make_setup())
    assert result["action"] in ("enter", "skip", "reject")


def test_high_ta_score_bullish_context_enters():
    engine = BayesianDecisionEngine(mode="normal")
    result = engine.decide(make_setup(ta_score=90, sentiment="bullish", rr_ratio=4.0))
    assert result["posterior"] >= MODE_THRESHOLDS["normal"]
    assert result["action"] == "enter"


def test_low_ta_score_bearish_rejects():
    engine = BayesianDecisionEngine(mode="normal")
    result = engine.decide(make_setup(ta_score=15, sentiment="bearish", risks=["high_risk_1", "high_risk_2", "high_risk_3"], rr_ratio=0.5))
    assert result["action"] in ("skip", "reject")


def test_safety_mode_raises_threshold():
    engine_normal = BayesianDecisionEngine(mode="normal")
    engine_safety = BayesianDecisionEngine(mode="safety")
    setup = make_setup(ta_score=70, sentiment="bullish")
    r_normal = engine_normal.decide(setup)
    r_safety = engine_safety.decide(setup)
    assert r_safety["threshold"] > r_normal["threshold"]


def test_update_prior_increases_on_win():
    engine = BayesianDecisionEngine(mode="normal")
    before = engine._priors["breakout"]
    engine.update_prior("breakout", won=True)
    assert engine._priors["breakout"] >= before


def test_update_prior_decreases_on_loss():
    engine = BayesianDecisionEngine(mode="normal")
    before = engine._priors["breakout"]
    engine.update_prior("breakout", won=False)
    assert engine._priors["breakout"] <= before


def test_update_prior_stays_bounded():
    engine = BayesianDecisionEngine(mode="normal")
    for _ in range(50):
        engine.update_prior("breakout", won=True)
    assert engine._priors["breakout"] <= 1.0
    for _ in range(50):
        engine.update_prior("momentum", won=False)
    assert engine._priors["momentum"] >= 0.0


def test_batch_decide_filters_non_enter():
    engine = BayesianDecisionEngine(mode="normal")
    setups = [
        make_setup(ta_score=90, sentiment="bullish", rr_ratio=4.0),
        make_setup(ta_score=5, sentiment="bearish", risks=["r1", "r2", "r3"], rr_ratio=0.2),
    ]
    approved = engine.batch_decide(setups)
    for s in approved:
        assert s["decision"]["action"] == "enter"


def test_high_risk_context_suppresses_posterior():
    engine = BayesianDecisionEngine(mode="normal")
    low_risk = make_setup(ta_score=45, sentiment="neutral", risks=[], vol_ratio=1.0, rr_ratio=1.5)
    high_risk = make_setup(ta_score=45, sentiment="neutral", risks=["r1", "r2", "r3", "r4"], vol_ratio=1.0, rr_ratio=1.5)
    r_low = engine.decide(low_risk)
    r_high = engine.decide(high_risk)
    assert r_high["posterior"] < r_low["posterior"]
