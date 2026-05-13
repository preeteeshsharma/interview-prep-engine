"""Tests for morning drill helpers.

Covers:
  Bug 1 — _days_until uses real scheduled_for, not hardcoded 7
  Bug 3 — _extract_day_section slices the correct Day N from a vault plan
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.jobs.morning_drill import _days_until, _extract_day_section, _first_heading


# ---------------------------------------------------------------------------
# _days_until — Bug 1
# ---------------------------------------------------------------------------

def test_days_until_returns_7_when_no_scheduled_for():
    assert _days_until(None) == 7


def test_days_until_computes_from_scheduled_for():
    future = datetime.now(timezone.utc) + timedelta(days=5)
    assert _days_until(future) == 5


def test_days_until_clamps_to_zero_for_past_interview():
    past = datetime.now(timezone.utc) - timedelta(days=3)
    assert _days_until(past) == 0


def test_days_until_never_negative():
    far_past = datetime.now(timezone.utc) - timedelta(days=365)
    assert _days_until(far_past) >= 0


def test_days_until_interview_tomorrow_is_one():
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    assert _days_until(tomorrow) == 1


# ---------------------------------------------------------------------------
# _extract_day_section — Bug 3
# ---------------------------------------------------------------------------

VAULT_PLAN = """\
# Prep Plan: Acme — Senior SWE
**Interview:** 2026-05-20
**Rounds:** DSA, LLD
**Generated:** 2026-05-13

---

## Day 1 — Foundational Data Structures

### DSA: Two Sum (LC 1)
- **Pattern / goal:** Hash map for O(n) lookup
- **Approach:** Iterate, check complement in map, return indices

---

## Day 2 — Sliding Window

### DSA: Longest Substring Without Repeating Characters (LC 3)
- **Pattern / goal:** Sliding window + hash set

---

## Day 3 — Trees & Graphs

### DSA: Binary Tree Level Order Traversal (LC 102)
- **Pattern / goal:** BFS with queue

---

## Weak areas to revisit
None identified yet.
"""


def test_extract_day_1_contains_correct_content():
    section = _extract_day_section(VAULT_PLAN, 1)
    assert section is not None
    assert "## Day 1" in section
    assert "Two Sum" in section


def test_extract_day_1_does_not_bleed_into_day_2():
    section = _extract_day_section(VAULT_PLAN, 1)
    assert "## Day 2" not in section
    assert "Sliding Window" not in section


def test_extract_day_2_is_isolated():
    section = _extract_day_section(VAULT_PLAN, 2)
    assert section is not None
    assert "## Day 2" in section
    assert "Longest Substring" in section
    assert "## Day 1" not in section
    assert "## Day 3" not in section


def test_extract_last_day_captures_to_end_of_plan():
    section = _extract_day_section(VAULT_PLAN, 3)
    assert section is not None
    assert "## Day 3" in section
    assert "Binary Tree" in section


def test_extract_day_beyond_plan_returns_none():
    assert _extract_day_section(VAULT_PLAN, 99) is None


def test_extract_day_from_empty_string_returns_none():
    assert _extract_day_section("", 1) is None


def test_extract_day_from_plan_with_no_day_headers_returns_none():
    assert _extract_day_section("# Just a title\nSome content\n### A drill", 1) is None


def test_extract_day_with_single_day_plan():
    single = "## Day 1 — Only Day\n### DSA: Foo\n- content"
    section = _extract_day_section(single, 1)
    assert section is not None
    assert "Only Day" in section


# ---------------------------------------------------------------------------
# _first_heading — drill label extraction (unchanged, regression guard)
# ---------------------------------------------------------------------------

def test_first_heading_finds_triple_hash():
    md = "## Day 1 — Topic\n### DSA: Two Sum (LC 1)\nsome content"
    assert _first_heading(md) == "DSA: Two Sum (LC 1)"


def test_first_heading_returns_none_when_absent():
    assert _first_heading("# No triple hash here\n## Day 1") is None


def test_first_heading_strips_hashes_and_whitespace():
    md = "###   Longest Substring (LC 3)  "
    assert _first_heading(md) == "Longest Substring (LC 3)"
