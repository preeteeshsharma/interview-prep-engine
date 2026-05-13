"""Tests for _fix_header — Bug 2: LLM hallucinates wrong year in plan header.

Haiku's training ends ~2024, so it sometimes writes 2024-MM-DD when told today is 2026-MM-DD.
_fix_header post-processes the plan markdown to inject Python-computed dates unconditionally.
"""
from app.tools.generate_plan import _fix_header


def test_fix_header_corrects_hallucinated_interview_date():
    plan_md = "# Prep Plan\n**Interview:** 2024-05-17\n**Generated:** 2024-05-12"
    fixed = _fix_header(plan_md, interview_date="2026-05-20", today="2026-05-13")
    assert "**Interview:** 2026-05-20" in fixed
    assert "2024-05-17" not in fixed


def test_fix_header_corrects_hallucinated_generated_date():
    plan_md = "# Prep Plan\n**Interview:** 2024-05-17\n**Generated:** 2024-05-12"
    fixed = _fix_header(plan_md, interview_date="2026-05-20", today="2026-05-13")
    assert "**Generated:** 2026-05-13" in fixed
    assert "2024-05-12" not in fixed


def test_fix_header_leaves_plan_body_intact():
    plan_md = (
        "# Prep Plan\n"
        "**Interview:** 2024-05-17\n"
        "**Generated:** 2024-05-12\n"
        "\n## Day 1 — Arrays\n### DSA: Two Sum (LC 1)"
    )
    fixed = _fix_header(plan_md, interview_date="2026-05-20", today="2026-05-13")
    assert "## Day 1 — Arrays" in fixed
    assert "Two Sum" in fixed


def test_fix_header_replaces_only_first_occurrence():
    """Only the first **Interview:** and **Generated:** lines are replaced."""
    plan_md = (
        "**Interview:** 2024-05-17\n"
        "**Generated:** 2024-05-12\n"
        "Some body that mentions **Interview:** again"
    )
    fixed = _fix_header(plan_md, interview_date="2026-05-20", today="2026-05-13")
    assert fixed.count("**Interview:**") == 2  # header replaced + body mention preserved
    assert "2026-05-20" in fixed


def test_fix_header_is_idempotent_on_correct_dates():
    plan_md = "# Prep Plan\n**Interview:** 2026-05-20\n**Generated:** 2026-05-13"
    fixed = _fix_header(plan_md, interview_date="2026-05-20", today="2026-05-13")
    assert "**Interview:** 2026-05-20" in fixed
    assert "**Generated:** 2026-05-13" in fixed


def test_fix_header_no_crash_when_header_lines_missing():
    """If the LLM omitted the header lines entirely, the function must not raise."""
    plan_md = "## Day 1 — Arrays\n### DSA: Two Sum (LC 1)"
    fixed = _fix_header(plan_md, interview_date="2026-05-20", today="2026-05-13")
    assert isinstance(fixed, str)
    assert "Day 1" in fixed
