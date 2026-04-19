import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.strategy_manager import compute_old_strategy_merge_cap


def test_compute_old_strategy_merge_cap_keeps_default_without_breakout():
    setups = [{"strategy": "mean_reversion", "setup_type": "pullback"}]

    assert compute_old_strategy_merge_cap(setups, max_positions=6) == 2


def test_compute_old_strategy_merge_cap_scales_breakout_orb_to_three_slots():
    setups = [
        {"strategy": "breakout", "setup_type": "breakout_orb"},
        {"strategy": "breakout", "setup_type": "breakout_orb"},
    ]

    assert compute_old_strategy_merge_cap(setups, max_positions=6) == 3
