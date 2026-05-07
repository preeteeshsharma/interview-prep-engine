"""Tests for Twilio intent handlers — mocks DB repos and external calls."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routes.webhooks.twilio import (
    _commit_plan_to_vault,
    _execute_prep,
    _handle_done,
    _handle_link,
    _handle_mock,
    _handle_status,
)
from app.tools.parse_prep_intent import PrepIntent


# ---------------------------------------------------------------------------
# _commit_plan_to_vault — return value
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_commit_plan_to_vault_returns_plan_path():
    """On success, returns the committed plan path string."""
    committed = []

    async def _fake_commit(path, content, message, github_token, vault_repo):
        committed.append(path)

    mock_ctx = MagicMock(github_token="tok", vault_repo="user/vault")

    with patch("app.routes.webhooks.twilio._get_ctx", new=AsyncMock(return_value=mock_ctx)), \
         patch("app.routes.webhooks.twilio.commit_file", side_effect=_fake_commit):
        result = await _commit_plan_to_vault(1, "Stripe", "plan content")

    assert result is not None
    assert result.endswith("-plan.md")
    assert result == committed[0]


@pytest.mark.asyncio
async def test_commit_plan_to_vault_returns_none_on_failure():
    """On any exception, returns None (vault failure must not crash the prep flow)."""
    with patch("app.routes.webhooks.twilio._get_ctx", new=AsyncMock(side_effect=Exception("network"))):
        result = await _commit_plan_to_vault(1, "Stripe", "plan content")

    assert result is None


# ---------------------------------------------------------------------------
# _execute_prep — idempotency guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prep_idempotency_skips_llm_when_active_plan_exists():
    """If an active plan exists and the date hasn't changed, LLM calls are skipped."""
    mock_interview = MagicMock()
    mock_interview.id = 1
    mock_interview.company = "Google"
    mock_interview.role = "L5 SWE"
    mock_interview.round_type = "DSA"
    mock_interview.scheduled_for = None

    mock_pending = MagicMock()
    mock_pending.id = 10

    mock_interview_repo = AsyncMock()
    mock_interview_repo.find_active_by_company_round.return_value = mock_interview

    mock_plan_repo = AsyncMock()
    mock_plan_repo.get_pending.return_value = mock_pending

    intent = PrepIntent(company="Google", role="L5 SWE", rounds=["DSA"], interview_date="2026-06-15")

    with patch("app.routes.webhooks.twilio.async_session_factory") as mock_factory, \
         patch("app.routes.webhooks.twilio.InterviewRepository", return_value=mock_interview_repo), \
         patch("app.routes.webhooks.twilio.PrepPlanRepository", return_value=mock_plan_repo), \
         patch("app.routes.webhooks.twilio.run_research", new=AsyncMock()) as mock_research, \
         patch("app.routes.webhooks.twilio.generate_plan", new=AsyncMock()) as mock_gen:
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _execute_prep("whatsapp:+91999", intent)

    mock_research.assert_not_called()
    mock_gen.assert_not_called()
    assert "already exists" in result.lower()


@pytest.mark.asyncio
async def test_prep_reruns_llm_when_date_changes():
    """If the interview date changed, the idempotency guard must not block re-generation."""
    from datetime import datetime, timezone

    mock_interview = MagicMock()
    mock_interview.id = 1
    mock_interview.company = "Google"
    mock_interview.role = "L5 SWE"
    mock_interview.round_type = "DSA"
    mock_interview.scheduled_for = datetime(2026, 5, 10, tzinfo=timezone.utc)  # old date

    mock_pending = MagicMock()
    mock_pending.id = 10

    mock_interview_repo = AsyncMock()
    mock_interview_repo.find_active_by_company_round.return_value = mock_interview

    mock_plan_repo = AsyncMock()
    mock_plan_repo.get_pending.return_value = mock_pending
    mock_plan_repo.create = AsyncMock()

    # New intent has a different date — should trigger regeneration.
    intent = PrepIntent(company="Google", role="L5 SWE", rounds=["DSA"], interview_date="2026-06-20")

    with patch("app.routes.webhooks.twilio.async_session_factory") as mock_factory, \
         patch("app.routes.webhooks.twilio.InterviewRepository", return_value=mock_interview_repo), \
         patch("app.routes.webhooks.twilio.PrepPlanRepository", return_value=mock_plan_repo), \
         patch("app.routes.webhooks.twilio.run_research", new=AsyncMock(return_value="research")) as mock_research, \
         patch("app.routes.webhooks.twilio.generate_plan", new=AsyncMock(return_value="# Plan\n### Two Pointers\n")) as mock_gen, \
         patch("app.routes.webhooks.twilio._commit_plan_to_vault", new=AsyncMock(return_value="google/dsa/123-plan.md")):
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        await _execute_prep("whatsapp:+91999", intent)

    mock_research.assert_called_once()
    mock_gen.assert_called_once()


# ---------------------------------------------------------------------------
# _handle_mock
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mock_requires_active_interview():
    """No active interview → clear error, no MockSession created."""
    with patch("app.routes.webhooks.twilio.async_session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.list_active.return_value = []

        with patch("app.routes.webhooks.twilio.InterviewRepository", return_value=mock_repo):
            result = await _handle_mock("whatsapp:+91999", ["lld"])

    assert "No active interview" in result
    assert "prep" in result.lower()


@pytest.mark.asyncio
async def test_mock_rejects_unknown_round_type():
    """Unknown round arg (LLM returns it as a round) → clear error."""
    from app.tools.parse_prep_intent import PrepIntent

    mock_interview = MagicMock()
    mock_interview.id = 1
    mock_interview.company = "Stripe"
    mock_interview.role = "Backend Engineer"
    mock_interview.round_type = "knitting"  # so _resolve_interview finds it

    with patch("app.routes.webhooks.twilio.async_session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.list_active.return_value = [mock_interview]

        # LLM identifies "knitting" as a round name (not a company).
        fake_intent = PrepIntent(company=None, rounds=["knitting"])

        with patch("app.routes.webhooks.twilio.InterviewRepository", return_value=mock_repo), \
             patch("app.routes.webhooks.twilio.parse_prep_intent", new=AsyncMock(return_value=fake_intent)):
            result = await _handle_mock("whatsapp:+91999", ["knitting"])

    assert "Unknown round" in result


@pytest.mark.asyncio
async def test_mock_defaults_to_behavioral_when_no_args():
    """No round arg → asks for round (new flow: ask once, default on reply)."""
    mock_interview = MagicMock()
    mock_interview.id = 1
    mock_interview.company = "Stripe"
    mock_interview.role = "Backend Engineer"

    with patch("app.routes.webhooks.twilio.async_session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_interview_repo = AsyncMock()
        mock_interview_repo.list_active.return_value = [mock_interview]

        mock_wa_repo = AsyncMock()

        from app.tools.parse_prep_intent import PrepIntent
        fake_intent = PrepIntent(company=None, rounds=None)

        with patch("app.routes.webhooks.twilio.InterviewRepository", return_value=mock_interview_repo), \
             patch("app.routes.webhooks.twilio.WaWindowRepository", return_value=mock_wa_repo), \
             patch("app.routes.webhooks.twilio.parse_prep_intent", new=AsyncMock(return_value=fake_intent)):
            result = await _handle_mock("whatsapp:+91999", [])

    # New flow: asks for round rather than defaulting silently
    assert "round" in result.lower() or "behavioral" in result.lower() or "session" in result.lower()


# ---------------------------------------------------------------------------
# _handle_done
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_done_rejects_invalid_rating():
    result = await _handle_done("whatsapp:+91999", ["amazing"])
    assert "Usage" in result
    assert "easy" in result


@pytest.mark.asyncio
async def test_done_no_args_rejects():
    result = await _handle_done("whatsapp:+91999", [])
    assert "Usage" in result


@pytest.mark.asyncio
async def test_done_no_active_interview():
    with patch("app.routes.webhooks.twilio.async_session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.list_active.return_value = []

        with patch("app.routes.webhooks.twilio.InterviewRepository", return_value=mock_repo):
            result = await _handle_done("whatsapp:+91999", ["hard"])

    assert "No active" in result


@pytest.mark.asyncio
async def test_done_disambiguation_shows_round_types():
    """When multiple active interviews exist, disambiguation prompt includes round types."""
    interview1 = MagicMock()
    interview1.id = 1
    interview1.company = "Google"
    interview1.role = "L5 SWE"
    interview1.round_type = "DSA"

    interview2 = MagicMock()
    interview2.id = 2
    interview2.company = "Stripe"
    interview2.role = "Senior Engineer"
    interview2.round_type = "sysdesign"

    with patch("app.routes.webhooks.twilio.async_session_factory") as mock_factory, \
         patch("app.routes.webhooks.twilio.WaWindowRepository") as mock_wa_cls:
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_wa_cls.return_value = AsyncMock()

        mock_repo = AsyncMock()
        mock_repo.list_active.return_value = [interview1, interview2]

        with patch("app.routes.webhooks.twilio.InterviewRepository", return_value=mock_repo):
            result = await _handle_done("whatsapp:+91999", ["easy"])

    assert "Which interview" in result
    # Round types must appear so the user can distinguish Google DSA/LLD from Stripe sysdesign.
    assert "DSA" in result or "LLD" in result
    assert "sysdesign" in result


@pytest.mark.asyncio
async def test_done_no_pending_plan():
    mock_interview = MagicMock()
    mock_interview.id = 1

    with patch("app.routes.webhooks.twilio.async_session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.list_active.return_value = [mock_interview]

        with patch("app.routes.webhooks.twilio.InterviewRepository", return_value=mock_repo):
            result = await _handle_done("whatsapp:+91999", ["easy"])

    assert "No pending" in result


# ---------------------------------------------------------------------------
# _handle_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_no_active_interviews():
    with patch("app.routes.webhooks.twilio.async_session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.list_active.return_value = []

        with patch("app.routes.webhooks.twilio.InterviewRepository", return_value=mock_repo):
            result = await _handle_status("whatsapp:+91999")

    assert "No active" in result


@pytest.mark.asyncio
async def test_status_lists_active_interviews():
    mock_interview = MagicMock()
    mock_interview.company = "Zapier"
    mock_interview.role = "Backend Engineer"
    mock_interview.round_type = "DSA"
    mock_interview.scheduled_for = None

    with patch("app.routes.webhooks.twilio.async_session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.list_active.return_value = [mock_interview]

        with patch("app.routes.webhooks.twilio.InterviewRepository", return_value=mock_repo):
            result = await _handle_status("whatsapp:+91999")

    assert "Zapier" in result
    assert "Backend Engineer" in result
    assert "DSA" in result


# ---------------------------------------------------------------------------
# _handle_link (V2 stub)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_link_no_email_returns_usage():
    result = await _handle_link("whatsapp:+91999", [])
    assert "Usage" in result


@pytest.mark.asyncio
async def test_link_with_email_returns_v2_message():
    result = await _handle_link("whatsapp:+91999", ["me@example.com"])
    assert "V2" in result or "owner" in result.lower()
