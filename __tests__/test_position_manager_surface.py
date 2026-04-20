import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.position_manager import PositionManager


REQUIRED_METHODS = (
    "get_all_positions",
    "get_position_for_symbol",
    "get_bot_exposure_usd",
)


def test_position_manager_exposes_required_methods():
    missing = [m for m in REQUIRED_METHODS if not hasattr(PositionManager, m)]
    assert not missing, (
        f"PositionManager is missing required methods: {missing}. "
        "Backend/server.py calls these — missing methods cause silent cycle errors."
    )
