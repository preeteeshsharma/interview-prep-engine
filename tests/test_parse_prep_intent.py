"""Tests for parse_prep_intent — round type canonical casing, alias fallback,
error isolation, and PrepIntent dataclass methods.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.parse_prep_intent import (
    PrepIntent,
    _map_label_to_round,
    parse_prep_intent,
)


# ---------------------------------------------------------------------------
# _map_label_to_round — pure function, no I/O
# ---------------------------------------------------------------------------

def test_map_exact_canonical_match():
    assert _map_label_to_round("DSA") == "DSA"
    assert _map_label_to_round("LLD") == "LLD"
    assert _map_label_to_round("sysdesign") == "sysdesign"
    assert _map_label_to_round("behavioral") == "behavioral"
    assert _map_label_to_round("hiring_manager") == "hiring_manager"


def test_map_alias_dsa_variants():
    assert _map_label_to_round("leetcode") == "DSA"
    assert _map_label_to_round("coding round") == "DSA"
    assert _map_label_to_round("technical screen") == "DSA"
    assert _map_label_to_round("Coding Ability and Problem Solving") == "DSA"
    assert _map_label_to_round("Data Structures and Algorithms") == "DSA"


def test_map_alias_lld_variants():
    assert _map_label_to_round("low level design") == "LLD"
    assert _map_label_to_round("object oriented design") == "LLD"
    assert _map_label_to_round("machine coding") == "LLD"


def test_map_alias_sysdesign_variants():
    assert _map_label_to_round("system design") == "sysdesign"
    assert _map_label_to_round("high level design") == "sysdesign"


def test_map_alias_behavioral_variants():
    assert _map_label_to_round("behavioural") == "behavioral"
    assert _map_label_to_round("culture fit") == "behavioral"
    assert _map_label_to_round("bar raiser") == "behavioral"
    assert _map_label_to_round("hr round") == "behavioral"


def test_map_alias_hiring_manager_variants():
    assert _map_label_to_round("hiring manager") == "hiring_manager"
    assert _map_label_to_round("hm round") == "hiring_manager"


def test_map_returns_none_for_unknown_label():
    assert _map_label_to_round("knitting") is None
    assert _map_label_to_round("random text") is None


# ---------------------------------------------------------------------------
# PrepIntent dataclass — pure logic
# ---------------------------------------------------------------------------

def test_missing_reports_all_gaps_when_empty():
    intent = PrepIntent()
    gaps = intent.missing()
    assert any("role" in g for g in gaps)
    assert any("date" in g for g in gaps)
    assert any("round" in g or "dsa" in g.lower() for g in gaps)


def test_missing_reports_no_gaps_when_complete():
    intent = PrepIntent(
        company="Stripe",
        role="Backend Engineer",
        interview_date="2026-06-15",
        rounds=["DSA"],
    )
    assert intent.missing() == []


def test_with_defaults_fills_missing_fields():
    intent = PrepIntent(company="Zapier")
    filled = intent.with_defaults()
    assert filled.role == "software engineer"
    assert filled.rounds is not None
    assert len(filled.rounds) > 0
    assert filled.days_until_interview == 7


def test_with_defaults_preserves_existing_fields():
    intent = PrepIntent(company="Stripe", role="SRE", interview_date="2026-07-01", rounds=["DSA"])
    filled = intent.with_defaults()
    assert filled.role == "SRE"
    assert filled.rounds == ["DSA"]


def test_merge_fills_from_second_intent():
    first = PrepIntent(company="Stripe")
    second = PrepIntent(role="Backend", interview_date="2026-06-15", rounds=["LLD"])
    merged = first.merge(second)
    assert merged.company == "Stripe"
    assert merged.role == "Backend"
    assert merged.interview_date == "2026-06-15"
    assert merged.rounds == ["LLD"]


def test_merge_first_intent_wins_on_conflict():
    first = PrepIntent(company="Stripe", role="Backend")
    second = PrepIntent(company="Google", role="SRE")
    merged = first.merge(second)
    assert merged.company == "Stripe"
    assert merged.role == "Backend"


def test_to_dict_and_from_dict_roundtrip():
    intent = PrepIntent(
        company="Fivetran",
        role="Senior SWE",
        interview_date="2026-06-20",
        days_until_interview=13,
        rounds=["DSA", "LLD"],
        round_labels=["Coding Ability", "Low Level Design"],
    )
    restored = PrepIntent.from_dict(intent.to_dict())
    assert restored.company == intent.company
    assert restored.role == intent.role
    assert restored.rounds == intent.rounds
    assert restored.round_labels == intent.round_labels


# ---------------------------------------------------------------------------
# parse_prep_intent — rounds must use canonical uppercase (DSA, LLD)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rounds_use_canonical_uppercase():
    """LLM returns 'DSA' and 'LLD' — they must pass the validity filter unchanged."""
    payload = json.dumps({
        "company": "Stripe",
        "role": "Backend Engineer",
        "interview_date": "2026-06-15",
        "days_until_interview": 8,
        "rounds": ["DSA", "LLD", "sysdesign"],
        "round_labels": None,
    })
    with patch("app.tools.parse_prep_intent.complete", new=AsyncMock(return_value=payload)):
        result = await parse_prep_intent("Stripe backend, june 15, coding and lld and system design")

    assert "DSA" in result.rounds
    assert "LLD" in result.rounds
    assert "sysdesign" in result.rounds


@pytest.mark.asyncio
async def test_lowercase_rounds_from_llm_are_filtered_and_alias_fallback_activates():
    """If LLM returns lowercase 'dsa'/'lld', the filter drops them and the alias
    fallback should kick in to recover from the original message."""
    payload = json.dumps({
        "company": "Stripe",
        "role": "Backend",
        "interview_date": None,
        "days_until_interview": None,
        "rounds": ["dsa", "lld"],  # wrong casing — should be filtered
        "round_labels": ["coding round", "low level design"],
    })
    with patch("app.tools.parse_prep_intent.complete", new=AsyncMock(return_value=payload)):
        result = await parse_prep_intent("Stripe backend, coding round and low level design")

    # Alias fallback must recover DSA and LLD.
    assert result.rounds is not None
    assert "DSA" in result.rounds
    assert "LLD" in result.rounds


@pytest.mark.asyncio
async def test_alias_fallback_from_round_labels():
    """When rounds is null but round_labels has recognisable labels, alias mapping fires."""
    payload = json.dumps({
        "company": "Google",
        "role": "SWE",
        "interview_date": "2026-07-01",
        "days_until_interview": 24,
        "rounds": None,
        "round_labels": ["Coding Ability and Problem Solving", "System Design"],
    })
    with patch("app.tools.parse_prep_intent.complete", new=AsyncMock(return_value=payload)):
        result = await parse_prep_intent("Google SWE, coding ability and system design")

    assert result.rounds is not None
    assert "DSA" in result.rounds
    assert "sysdesign" in result.rounds


@pytest.mark.asyncio
async def test_llm_failure_returns_empty_intent():
    with patch("app.tools.parse_prep_intent.complete", new=AsyncMock(side_effect=RuntimeError("LLM down"))):
        result = await parse_prep_intent("Stripe backend")

    assert result == PrepIntent()
    assert result.company is None
    assert result.rounds is None


@pytest.mark.asyncio
async def test_bad_json_returns_empty_intent():
    with patch("app.tools.parse_prep_intent.complete", new=AsyncMock(return_value="not valid json")):
        result = await parse_prep_intent("Stripe backend")

    assert result == PrepIntent()


@pytest.mark.asyncio
async def test_partial_parse_missing_rounds():
    payload = json.dumps({
        "company": "Fivetran",
        "role": "Senior Backend",
        "interview_date": "2026-06-20",
        "days_until_interview": 13,
        "rounds": None,
        "round_labels": None,
    })
    with patch("app.tools.parse_prep_intent.complete", new=AsyncMock(return_value=payload)):
        result = await parse_prep_intent("Fivetran senior backend june 20")

    assert result.company == "Fivetran"
    assert result.role == "Senior Backend"
    assert result.rounds is None
    assert "round" in " ".join(result.missing()).lower()


@pytest.mark.asyncio
async def test_deduplicates_rounds_from_alias_fallback():
    """Two labels that map to the same canonical type should not produce duplicates."""
    payload = json.dumps({
        "company": "Test",
        "role": "SWE",
        "interview_date": None,
        "days_until_interview": None,
        "rounds": None,
        "round_labels": ["leetcode", "coding round"],  # both → DSA
    })
    with patch("app.tools.parse_prep_intent.complete", new=AsyncMock(return_value=payload)):
        result = await parse_prep_intent("Test, leetcode and coding round")

    assert result.rounds is not None
    assert result.rounds.count("DSA") == 1
