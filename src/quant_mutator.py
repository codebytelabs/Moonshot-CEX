"""
QuantMutator — Adaptive strategy self-tuning.
Adjusts confidence thresholds and score requirements based on rolling win rate + PnL feedback.
Mutations are logged for full audit trail.
"""
import time
from typing import Optional
from loguru import logger


class QuantMutator:
    """Self-tunes Bayesian thresholds and watcher min_score based on performance."""

    def __init__(
        self,
        every_n_cycles: int = 5,
        high_win_rate: float = 0.65,
        low_win_rate: float = 0.40,
        min_closed_trades: int = 5,
        score_raise_step: float = 5.0,
        score_lower_step: float = 3.0,
        min_score_floor: float = 15.0,
        min_score_ceiling: float = 60.0,
    ):
        self.every_n_cycles = every_n_cycles
        self.high_win_rate = high_win_rate
        self.low_win_rate = low_win_rate
        self.min_closed_trades = min_closed_trades
        self.score_raise_step = score_raise_step
        self.score_lower_step = score_lower_step
        self.min_score_floor = min_score_floor
        self.min_score_ceiling = min_score_ceiling

        self._cycle_count = 0
        self._mutations: list[dict] = []

    def maybe_mutate(
        self,
        current_min_score: float,
        current_bayesian_threshold: float,
        closed_trades: list[dict],
        current_day_pnl_pct: float = 0.0,
    ) -> dict:
        """
        Check if mutation is warranted this cycle.
        Returns {min_score, bayesian_threshold, mutated: bool}.
        """
        self._cycle_count += 1

        if self._cycle_count % self.every_n_cycles != 0:
            return {
                "min_score": current_min_score,
                "bayesian_threshold": current_bayesian_threshold,
                "mutated": False,
            }

        recent = closed_trades[-20:] if len(closed_trades) >= 20 else closed_trades
        if len(recent) < self.min_closed_trades:
            return {
                "min_score": current_min_score,
                "bayesian_threshold": current_bayesian_threshold,
                "mutated": False,
            }

        wins = sum(1 for t in recent if t.get("pnl_usd", 0) > 0)
        win_rate = wins / len(recent)

        new_score = current_min_score
        new_threshold = current_bayesian_threshold
        reason = ""

        # Emergency: today's PnL deeply negative → raise bars (but cap at ceiling)
        if current_day_pnl_pct < -0.05:
            new_score = min(self.min_score_ceiling, current_min_score + self.score_raise_step * 2)
            new_threshold = min(0.90, current_bayesian_threshold + 0.05)
            reason = f"emergency_pnl ({current_day_pnl_pct:.1%})"

        elif win_rate >= self.high_win_rate:
            # Hot streak → slightly lower bars to capture more trades
            new_score = max(self.min_score_floor, current_min_score - self.score_lower_step)
            new_threshold = max(0.12, current_bayesian_threshold - 0.02)
            reason = f"hot_streak (wr={win_rate:.0%})"

        elif win_rate < self.low_win_rate:
            # Cold streak → raise bars to reduce trading (but cap at ceiling)
            new_score = min(self.min_score_ceiling, current_min_score + self.score_raise_step)
            new_threshold = min(0.88, current_bayesian_threshold + 0.03)
            reason = f"cold_streak (wr={win_rate:.0%})"
        
        # Hard cap enforcement for momentum hunting (never exceed ceiling)
        new_score = min(self.min_score_ceiling, new_score)

        mutated = (new_score != current_min_score or new_threshold != current_bayesian_threshold)

        if mutated:
            mutation = {
                "cycle": self._cycle_count,
                "reason": reason,
                "win_rate": round(win_rate, 4),
                "day_pnl_pct": round(current_day_pnl_pct, 4),
                "before": {
                    "min_score": current_min_score,
                    "bayesian_threshold": current_bayesian_threshold,
                },
                "after": {
                    "min_score": new_score,
                    "bayesian_threshold": new_threshold,
                },
                "timestamp": int(time.time()),
            }
            self._mutations.append(mutation)
            if len(self._mutations) > 200:
                self._mutations = self._mutations[-200:]

            logger.info(
                f"[QuantMutator] {reason}: "
                f"min_score {current_min_score:.1f}→{new_score:.1f} "
                f"threshold {current_bayesian_threshold:.2f}→{new_threshold:.2f}"
            )

        return {
            "min_score": round(new_score, 2),
            "bayesian_threshold": round(new_threshold, 3),
            "mutated": mutated,
            "win_rate": round(win_rate, 4),
            "reason": reason if mutated else "no_change",
        }

    def get_mutation_history(self, n: int = 20) -> list[dict]:
        return self._mutations[-n:]
