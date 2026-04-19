import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.analyzer import AnalyzerAgent


def make_analyzer() -> AnalyzerAgent:
    return AnalyzerAgent(exchange=MagicMock(), redis=None)


def test_finalize_setup_type_blocks_neutral_without_fast_track():
    analyzer = make_analyzer()

    assert analyzer._finalize_setup_type("neutral", False) is None


def test_finalize_setup_type_preserves_fast_track_and_explicit_setup():
    analyzer = make_analyzer()

    assert analyzer._finalize_setup_type("neutral", True) == "momentum"
    assert analyzer._finalize_setup_type("breakout", False) == "breakout"
