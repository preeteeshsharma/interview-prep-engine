"""Tests for PrepPlanRepository — auto-skip on create, get_pending."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models import PrepPlan
from app.db.repos.prep_plans import PrepPlanRepository


@pytest.mark.asyncio
async def test_create_executes_skip_update_before_insert():
    """create() must issue an UPDATE skipped=True before inserting the new plan."""
    executed = []
    added = []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=lambda stmt: executed.append(stmt))
    mock_session.add = MagicMock(side_effect=lambda obj: added.append(obj))
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    await PrepPlanRepository(mock_session).create(interview_id=1, time_budget_min=120)

    # One UPDATE statement (the skip) must have fired.
    assert len(executed) == 1
    # One new PrepPlan must have been staged for insert.
    assert len(added) == 1
    assert isinstance(added[0], PrepPlan)


@pytest.mark.asyncio
async def test_create_new_plan_is_not_skipped():
    """The newly created plan must not be pre-skipped."""
    added = []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.add = MagicMock(side_effect=lambda obj: added.append(obj))
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    await PrepPlanRepository(mock_session).create(interview_id=5, time_budget_min=60)

    assert not added[0].skipped  # None (not yet committed) is falsy — new plan is not skipped
    assert added[0].interview_id == 5


@pytest.mark.asyncio
async def test_create_stores_vault_path_and_drill_label():
    """vault_path and drill_label are persisted on the new plan row."""
    added = []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.add = MagicMock(side_effect=lambda obj: added.append(obj))
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    await PrepPlanRepository(mock_session).create(
        interview_id=3,
        time_budget_min=120,
        vault_path="google/dsa/1778165199-plan.md",
        drill_label="Two Pointers",
    )

    plan = added[0]
    assert plan.vault_path == "google/dsa/1778165199-plan.md"
    assert plan.drill_label == "Two Pointers"


@pytest.mark.asyncio
async def test_get_pending_returns_none_when_no_plans():
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await PrepPlanRepository(mock_session).get_pending(interview_id=1)

    assert result is None
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_pending_returns_plan_when_present():
    mock_plan = MagicMock(spec=PrepPlan)
    mock_plan.id = 42

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_plan

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await PrepPlanRepository(mock_session).get_pending(interview_id=7)

    assert result is mock_plan
