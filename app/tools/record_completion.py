from __future__ import annotations

from app.db.repos.prep_plans import PrepPlanRepository
from app.db.repos.weak_patterns import WeakPatternRepository
from app.db.session import async_session_factory
from app.lib.logging import get_logger

logger = get_logger(__name__)

# Hard/skipped drills surface more aggressively in the next prep run.
_WEIGHT_BUMP: dict[str, float] = {
    "easy": 0.0,
    "medium": 0.5,
    "hard": 1.5,
}


async def record_completion(plan_id: int, rating: str) -> str:
    """Mark a prep plan complete and bump weak_patterns if rating is medium/hard.

    Returns a reply string to send back to the user via WhatsApp.
    """
    rating = rating.lower().strip()
    if rating not in _WEIGHT_BUMP:
        return f"Unknown rating '{rating}'. Reply: done easy / done medium / done hard."

    async with async_session_factory() as session:
        plan = await PrepPlanRepository(session).mark_complete(plan_id, rating)

        weight_bump = _WEIGHT_BUMP[rating]
        if weight_bump > 0:
            pattern = _extract_pattern(plan.plan_md, rating)
            if pattern:
                await WeakPatternRepository(session).upsert(
                    pattern=pattern,
                    weight_bump=weight_bump,
                    session_id=None,
                )
                logger.info("record_completion.pattern_bumped", pattern=pattern, bump=weight_bump)

    msgs = {
        "easy": "✅ Marked easy — moving on.",
        "medium": "📈 Marked medium — noted for review.",
        "hard": "🔥 Marked hard — I'll prioritise this area in your next drill.",
    }
    return msgs[rating]


def _extract_pattern(plan_md: str, rating: str) -> str | None:
    """Extract a rough label from the plan markdown to store as a weak pattern."""
    for line in plan_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("### "):
            label = stripped.lstrip("# ").strip()
            return f"{label} ({rating})"
    return None
