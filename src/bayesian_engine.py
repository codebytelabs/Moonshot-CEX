"""
BayesianDecisionEngine — Probabilistic trade decision making.
Combines TA score, ML features, and market context into a posterior probability.
Updates priors online after each trade outcome.
"""
import math
import time
from typing import Optional
from loguru import logger

from .metrics import decisions_made


SETUP_PRIORS = {
    "breakout": 0.62,
    "momentum": 0.58,
    "pullback": 0.55,
    # mean_reversion is contrarian — conflicts with momentum thesis. Low prior so
    # that only very strong evidence (high TA score + volume spike) can pass 0.65 threshold.
    "mean_reversion": 0.38,
    "consolidation_breakout": 0.60,
    "neutral": 0.45,
}

MODE_THRESHOLDS = {
    "normal": 0.65,
    "volatile": 0.75,
    "safety": 0.85,
}


class BayesianDecisionEngine:
    """Bayesian inference for trade entry decisions with online learning."""

    def __init__(
        self,
        mode: str = "normal",
        threshold_normal: Optional[float] = None,
        threshold_volatile: Optional[float] = None,
        threshold_safety: Optional[float] = None,
    ):
        self.mode = mode
        self._priors = dict(SETUP_PRIORS)
        self._outcome_history: list[dict] = []
        self._thresholds = dict(MODE_THRESHOLDS)
        if threshold_normal is not None:
            self._thresholds["normal"] = threshold_normal
        if threshold_volatile is not None:
            self._thresholds["volatile"] = threshold_volatile
        if threshold_safety is not None:
            self._thresholds["safety"] = threshold_safety

    def set_mode(self, mode: str):
        if mode in MODE_THRESHOLDS:
            self.mode = mode

    def decide(self, setup: dict) -> dict:
        """
        Make a trade decision for a single setup.
        Returns {action: 'enter'|'skip'|'reject', posterior: float, reasoning: str}
        """
        symbol = setup.get("symbol", "?")
        setup_type = setup.get("setup_type", "neutral")
        ta_score = float(setup.get("ta_score", 0.0))
        entry_zone = setup.get("entry_zone") or {}
        rr_ratio = float(entry_zone.get("rr_ratio", 0.0))
        context = setup.get("context") or {}

        prior = self._priors.get(setup_type, 0.45)

        ta_likelihood = _sigmoid(ta_score, midpoint=45.0, steepness=0.08)

        sentiment = context.get("sentiment", "neutral")
        ctx_confidence = float(context.get("confidence", 0.5))
        driver_type = context.get("driver_type", "unknown")
        catalyst_count = len(context.get("catalysts", []))
        risk_count = len(context.get("risks", []))

        if sentiment == "bullish":
            ctx_base = 0.6 + ctx_confidence * 0.3
        elif sentiment == "bearish":
            ctx_base = 0.3 - ctx_confidence * 0.2
        else:
            # When context agent is disabled (neutral + no catalysts + no risks),
            # use neutral-positive baseline so Bayesian isn't artificially penalized
            ctx_base = 0.65 if (catalyst_count == 0 and risk_count == 0) else 0.5

        narrative_bonus = 0.05 if driver_type in ("narrative", "fundamental") else 0.0
        ctx_likelihood = min(0.95, ctx_base + narrative_bonus + catalyst_count * 0.02)

        vol_spike = max(1.0, float(setup.get("vol_ratio", 1.0)) if "vol_ratio" in setup else 1.0)
        vol_likelihood = _sigmoid(vol_spike * 50, midpoint=50.0, steepness=0.05)

        rr_factor = min(1.0, 0.5 + rr_ratio / 6.0)

        combined_likelihood = ta_likelihood * ctx_likelihood * vol_likelihood * rr_factor

        # ── Proper Bayesian posterior ──────────────────────────────────────────
        # P(success | evidence) = P(evidence | success) * P(success) / P(evidence)
        # Replaces the arbitrary × 6.5 multiplier with calibrated Bayes theorem.
        # P(evidence | failure) ≈ 1 - combined_likelihood  (complementary assumption)
        numerator = prior * combined_likelihood
        denominator = numerator + (1.0 - prior) * (1.0 - combined_likelihood)
        posterior = numerator / denominator if denominator > 1e-9 else prior

        # Risk adjustments (applied as additive penalties in probability space)
        risk_penalty = min(0.25, risk_count * 0.07)
        posterior -= risk_penalty

        if ta_score < 20.0:
            posterior -= 0.12
        if rr_ratio < 1.0:
            posterior -= 0.08

        posterior = max(0.0, min(1.0, posterior))

        threshold = self._thresholds.get(self.mode, 0.65)

        if posterior >= threshold:
            action = "enter"
        elif posterior >= threshold * 0.80:
            action = "skip"
        else:
            action = "reject"

        reasoning = (
            f"setup={setup_type} prior={prior:.2f} "
            f"ta={ta_likelihood:.2f} ctx={ctx_likelihood:.2f} "
            f"vol={vol_likelihood:.2f} rr={rr_factor:.2f} "
            f"posterior={posterior:.3f} threshold={threshold:.2f} → {action}"
        )

        decisions_made.labels(outcome=action).inc()
        logger.debug(f"[Bayes] {symbol}: {reasoning}")

        return {
            "action": action,
            "posterior": round(posterior, 4),
            "threshold": threshold,
            "prior": prior,
            "setup_type": setup_type,
            "ta_likelihood": round(ta_likelihood, 4),
            "ctx_likelihood": round(ctx_likelihood, 4),
            "vol_likelihood": round(vol_likelihood, 4),
            "rr_factor": round(rr_factor, 4),
            "reasoning": reasoning,
            "timestamp": int(time.time()),
        }

    def batch_decide(self, setups: list[dict]) -> list[dict]:
        """Process multiple setups and return those with action='enter'."""
        results = []
        for setup in setups:
            decision = self.decide(setup)
            if decision["action"] == "enter":
                results.append(dict(setup, decision=decision))
        return results

    def update_prior(self, setup_type: str, won: bool):
        """Online update of setup-type prior after trade outcome."""
        if setup_type not in self._priors:
            return
        alpha = 0.05
        outcome = 1.0 if won else 0.0
        current = self._priors[setup_type]
        self._priors[setup_type] = round(current * (1 - alpha) + outcome * alpha, 4)
        self._outcome_history.append({
            "setup_type": setup_type,
            "won": won,
            "new_prior": self._priors[setup_type],
            "timestamp": int(time.time()),
        })
        if len(self._outcome_history) > 500:
            self._outcome_history = self._outcome_history[-500:]

    def get_status(self) -> dict:
        return {
            "mode": self.mode,
            "threshold": self._thresholds.get(self.mode, 0.65),
            "priors": dict(self._priors),
            "outcome_history_count": len(self._outcome_history),
        }


def _sigmoid(x: float, midpoint: float = 50.0, steepness: float = 0.1) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (x - midpoint)))
    except OverflowError:
        return 0.0 if x < midpoint else 1.0
