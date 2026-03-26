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
        consecutive_zero_setups: int = 0,
    ) -> dict:
        """
        Check if mutation is warranted this cycle.
        Returns {min_score, bayesian_threshold, mutated: bool}.
        """
        self._cycle_count += 1

        # ── Drought relief: system frozen with 0 setups for too long ──────────
        # If no setup passes the filter for >200 consecutive cycles (~1.7h), the
        # bars are too high. Force them back down so trading can resume.
        DROUGHT_CYCLES = 200
        if consecutive_zero_setups > DROUGHT_CYCLES:
            relief_score = max(self.min_score_floor, current_min_score - self.score_raise_step * 2)
            relief_threshold = max(0.40, current_bayesian_threshold - 0.10)
            mutated = (relief_score != current_min_score or relief_threshold != current_bayesian_threshold)
            if mutated:
                logger.info(
                    f"[QuantMutator] drought_relief ({consecutive_zero_setups} zero-setup cycles): "
                    f"min_score {current_min_score:.1f}→{relief_score:.1f} "
                    f"threshold {current_bayesian_threshold:.2f}→{relief_threshold:.2f}"
                )
            return {
                "min_score": round(relief_score, 2),
                "bayesian_threshold": round(relief_threshold, 3),
                "mutated": mutated,
                "win_rate": 0.0,
                "reason": f"drought_relief ({consecutive_zero_setups} cycles)" if mutated else "no_change",
            }

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

        # Emergency: today's PnL deeply negative → modest raise only, never lockout
        # Cap threshold at 0.45 — don't let emergency mode create garbage entries
        if current_day_pnl_pct < -0.05:
            new_score = min(self.min_score_ceiling, current_min_score + self.score_raise_step)
            new_threshold = min(0.45, current_bayesian_threshold + 0.02)
            reason = f"emergency_pnl ({current_day_pnl_pct:.1%})"

        elif win_rate >= self.high_win_rate:
            # Hot streak → slightly lower bars, but NEVER below 0.40.
            # Old floor of 0.12 let every garbage setup through → 185 trades/day,
            # 11 stop losses, 92 time exits. Bayesian < 0.40 is meaningless noise.
            new_score = max(self.min_score_floor, current_min_score - self.score_lower_step)
            new_threshold = max(0.40, current_bayesian_threshold - 0.02)
            reason = f"hot_streak (wr={win_rate:.0%})"

        elif win_rate < self.low_win_rate:
            # Cold streak → raise score bar, but:
            # 1. Don't raise Bayesian when score is already at ceiling — system can't enter
            #    anyway, and raising Bayesian just makes the freeze harder to break out of.
            # 2. Cap Bayesian at 0.62 — Bayesian prior is 0.48-0.62; higher is unreachable.
            new_score = min(self.min_score_ceiling, current_min_score + self.score_raise_step)
            if current_min_score < self.min_score_ceiling:
                new_threshold = min(0.62, current_bayesian_threshold + 0.02)
            else:
                new_threshold = current_bayesian_threshold  # frozen at ceiling — don't raise further
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
