"""Tests for record_completion pure helpers — no DB or API calls."""
from app.tools.record_completion import _extract_pattern, _WEIGHT_BUMP


def test_extract_pattern_finds_first_heading():
    plan = "# Prep Plan\n\n## Day 1\n\n### DSA: Two Sum\n- Goal: sliding window\n"
    result = _extract_pattern(plan, "hard")
    assert result == "DSA: Two Sum (hard)"


def test_extract_pattern_no_heading_returns_none():
    plan = "Some text with no headings at all."
    assert _extract_pattern(plan, "hard") is None


def test_extract_pattern_uses_rating():
    plan = "### LLD: Music Player\n- Approach: State pattern\n"
    assert _extract_pattern(plan, "medium") == "LLD: Music Player (medium)"


def test_extract_pattern_skips_h1_h2():
    plan = "# Title\n## Section\n### DSA: BFS\n"
    assert _extract_pattern(plan, "easy") == "DSA: BFS (easy)"


def test_weight_bump_easy_is_zero():
    assert _WEIGHT_BUMP["easy"] == 0.0


def test_weight_bump_medium_positive():
    assert _WEIGHT_BUMP["medium"] > 0


def test_weight_bump_hard_greater_than_medium():
    assert _WEIGHT_BUMP["hard"] > _WEIGHT_BUMP["medium"]


def test_all_valid_ratings_present():
    assert set(_WEIGHT_BUMP.keys()) == {"easy", "medium", "hard"}
