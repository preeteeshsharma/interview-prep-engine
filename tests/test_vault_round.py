"""Tests for _get_vault_round — Bug 5: daily-plan vault paths must return correct round slug.

A daily plan written by the morning cron uses a 2-segment path (plans/company-date.md).
The second segment is NOT a round slug, so the old code fell back to interview.round_type
which could differ from the actual vault directory name (e.g. "coding" vs
"coding-ability-and-problem-solving"). The fix looks up the original structured plan for
the correct slug.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import PrepPlan
from app.routes.webhooks.twilio import _get_vault_round


def _make_session(pending_plan, structured_plan=None):
    """Wire a mock PrepPlanRepository that returns the given plans."""
    mock_repo = AsyncMock()
    mock_repo.get_pending.return_value = pending_plan
    mock_repo.get_structured.return_value = structured_plan

    mock_session = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    return mock_factory, mock_repo


@pytest.mark.asyncio
async def test_structured_path_returns_parts_1_as_slug():
    """3-segment vault_path (company/round/epoch.md) returns parts[1] directly."""
    plan = MagicMock(spec=PrepPlan)
    plan.vault_path = "moveworks/coding/1778217855-plan.md"

    mock_factory, mock_repo = _make_session(pending_plan=plan)

    with patch("app.routes.webhooks.twilio.async_session_factory", mock_factory), \
         patch("app.routes.webhooks.twilio.PrepPlanRepository", return_value=mock_repo):
        result_plan, slug = await _get_vault_round(1, fallback="general")

    assert slug == "coding"
    assert result_plan is plan


@pytest.mark.asyncio
async def test_daily_path_falls_back_to_structured_slug():
    """Daily-format pending plan (2 segments) retrieves slug from structured plan."""
    pending = MagicMock(spec=PrepPlan)
    pending.vault_path = "plans/fivetran-2026-05-13.md"

    structured = MagicMock(spec=PrepPlan)
    structured.vault_path = "fivetran/coding-ability-and-problem-solving/1778175817-plan.md"

    mock_factory, mock_repo = _make_session(pending_plan=pending, structured_plan=structured)

    with patch("app.routes.webhooks.twilio.async_session_factory", mock_factory), \
         patch("app.routes.webhooks.twilio.PrepPlanRepository", return_value=mock_repo):
        result_plan, slug = await _get_vault_round(1, fallback="general")

    # Slug comes from the structured plan, not from fallback.
    assert slug == "coding-ability-and-problem-solving"
    # Pending plan returned so callers can track completion against the right row.
    assert result_plan is pending


@pytest.mark.asyncio
async def test_daily_path_no_structured_plan_returns_fallback():
    """When there is no structured plan, fall back to the caller-supplied slug."""
    pending = MagicMock(spec=PrepPlan)
    pending.vault_path = "plans/moveworks-2026-05-13.md"

    mock_factory, mock_repo = _make_session(pending_plan=pending, structured_plan=None)

    with patch("app.routes.webhooks.twilio.async_session_factory", mock_factory), \
         patch("app.routes.webhooks.twilio.PrepPlanRepository", return_value=mock_repo):
        result_plan, slug = await _get_vault_round(1, fallback="dsa")

    assert slug == "dsa"
    assert result_plan is pending


@pytest.mark.asyncio
async def test_no_pending_plan_returns_fallback_and_none():
    """No pending plan at all returns (None, fallback)."""
    mock_factory, mock_repo = _make_session(pending_plan=None)

    with patch("app.routes.webhooks.twilio.async_session_factory", mock_factory), \
         patch("app.routes.webhooks.twilio.PrepPlanRepository", return_value=mock_repo):
        result_plan, slug = await _get_vault_round(1, fallback="coding")

    assert result_plan is None
    assert slug == "coding"


@pytest.mark.asyncio
async def test_structured_path_with_multi_segment_round_slug():
    """Round slugs with hyphens (e.g. 'coding-ability-and-problem-solving') are preserved."""
    plan = MagicMock(spec=PrepPlan)
    plan.vault_path = "fivetran/coding-ability-and-problem-solving/1778175817-plan.md"

    mock_factory, mock_repo = _make_session(pending_plan=plan)

    with patch("app.routes.webhooks.twilio.async_session_factory", mock_factory), \
         patch("app.routes.webhooks.twilio.PrepPlanRepository", return_value=mock_repo):
        _, slug = await _get_vault_round(1, fallback="general")

    assert slug == "coding-ability-and-problem-solving"
