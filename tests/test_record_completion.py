"""Tests for record_completion constants."""
from app.tools.record_completion import _WEIGHT_BUMP


def test_weight_bump_easy_is_zero():
    assert _WEIGHT_BUMP["easy"] == 0.0


def test_weight_bump_medium_positive():
    assert _WEIGHT_BUMP["medium"] > 0


def test_weight_bump_hard_greater_than_medium():
    assert _WEIGHT_BUMP["hard"] > _WEIGHT_BUMP["medium"]


def test_all_valid_ratings_present():
    assert set(_WEIGHT_BUMP.keys()) == {"easy", "medium", "hard"}
