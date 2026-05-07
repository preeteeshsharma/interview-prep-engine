from __future__ import annotations

from app.db.repos.prep_plans import PrepPlanRepository
from app.db.repos.weak_patterns import WeakPatternRepository
from app.db.session import async_session_factory
from app.lib.logging import get_logger

logger = get_logger(__name__)

_WEIGHT_BUMP: dict[str, float] = {
    "easy": 0.0,
    "medium": 0.5,
    "hard": 1.5,
}

_MESSAGES: dict[str, str] = {
    "easy": "Marked easy — moving on.",
    "medium": "Marked medium — noted for review.",
    "hard": "Marked hard — I'll prioritise this in your next drill.",
}


async def record_completion(plan_id: int, rating: str) -> str:
    """Mark a prep plan complete, bump weak pattern weight if medium/hard."""
    rating = rating.lower().strip()
    if rating not in _WEIGHT_BUMP:
        return f"Unknown rating '{rating}'. Reply: done easy / done medium / done hard."

    async with async_session_factory() as session:
        plan = await PrepPlanRepository(session).mark_complete(plan_id, rating)

        weight_bump = _WEIGHT_BUMP[rating]
        if weight_bump > 0 and plan.drill_label:
            await WeakPatternRepository(session).upsert(
                pattern=f"{plan.drill_label} ({rating})",
                weight_bump=weight_bump,
            )
            logger.info("record_completion.pattern_bumped", pattern=plan.drill_label, bump=weight_bump)

    return _MESSAGES[rating]
