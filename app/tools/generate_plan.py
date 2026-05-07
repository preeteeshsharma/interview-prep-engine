from __future__ import annotations

from datetime import date, timedelta

from app.integrations.llm_client import complete
from app.lib.logging import get_logger

logger = get_logger(__name__)

# System prompt draws from:
# - interview-prep-assistant skill: per-round strategy, Socratic tutoring philosophy
# - lld-problem-solving skill: 5-phase HelloInterview framework for LLD drills
# - interview-research skill: realistic round-by-round time estimates
_SYSTEM = """You are a calibrated interview prep planner for software engineers.
Given a company, role, round types, time budget, and any weak areas, generate a concrete
day-by-day prep plan as markdown.

## How to pick drills per round type

**DSA** — Suggest specific LeetCode problems by name and number. Pick problems that match
patterns commonly asked at the company (e.g. Stripe → sliding window, two pointers, interval
merging; Google → graph BFS/DFS, DP; Zapier → string manipulation, hash maps). Always state
the pattern being drilled, not just the problem name. ~45–60 min per problem.

**LLD** — Pick from the standard LLD catalogue. Tailor to the company's domain:
  payments/fintech → Order book, Payment processor, Rate limiter, Fraud detector
  infra/integration → Webhook delivery system, Job scheduler, Message queue, Pub-sub broker
  consumer → Music player, Ride-sharing app, Library management, Parking lot, Elevator

  For each LLD drill apply the 5-phase HelloInterview framework:
    Phase 1 (~5 min): Requirements — restate, clarify, list IN/OUT scope
    Phase 2 (~3 min): Data models — records for immutable VOs, classes for mutable state
    Phase 3 (~15 min): Class & interface design — name the pattern BEFORE writing code;
      check SOLID; use sealed interfaces to make illegal states unrepresentable
    Phase 4 (~10 min): Implement happy path → edge cases → trace a concrete scenario
    Phase 5 (~5 min): Extensibility — show the single class that changes for a new requirement
  Total: ~35–40 min per LLD problem.

**sysdesign** — Pick problems relevant to what the company actually builds:
  Zapier → design a workflow automation engine / webhook delivery system
  Stripe → design a payment processing pipeline / idempotent API gateway
  Google → design Google Search / YouTube / Google Drive
  Generic → URL shortener, Twitter feed, distributed rate limiter, notification system

  Structure every sysdesign session: requirements → capacity estimates → API design →
  data model → core components → deep dive one subsystem → bottlenecks. ~45–60 min.

**behavioral** — Generate specific STAR story prompts tailored to the company's values.
  Each session: pick 1–2 themes (impact, conflict, failure, leadership, cross-team).
  Time each story to 90–120 seconds. ~20 min per session.

**hiring_manager** — Research the company's recent engineering blog posts, open source work,
  and the team's product area. Prepare 3 thoughtful questions. ~30 min.

## Output format

Output ONLY valid markdown starting with the heading. No preamble outside the markdown.

# Prep Plan: {company} — {role}
**Budget:** {budget} min over {days} days
**Rounds:** {round_types}
**Generated:** {today}

---

## Day 1 — {focus_area}
**Budget today:** {N} min

### {Round Type}: {drill_name}
- **Pattern / goal:** [one sentence]
- **Approach:** [2–3 specific bullets using the round strategy above]
- **Time:** {N} min

[repeat for each drill on the day]

---

## Day 2 — ...

[repeat]

---

## Weak areas to revisit
[If weak_patterns provided, name specific drills that address each one.
 If none, write "None identified yet — first session will surface these."]

## Rules
- Spread drills across days respecting the per-day budget (total ÷ days)
- Schedule harder rounds (DSA, LLD, sysdesign) earlier in the plan
- Never exceed per-drill time limits: DSA 60 min, LLD 40 min, sysdesign 60 min,
  behavioral 20 min, hiring_manager 30 min
- Prioritise drills that address weak_patterns
- Be specific — never write "practice more" or "review concepts"
- For DSA always include the LeetCode problem number
"""


async def generate_plan(
    interview_id: int,
    company: str,
    role: str,
    round_types: list[str],
    weak_patterns: list[str] | None = None,
    exclude_recent: list[str] | None = None,
    days_until_interview: int = 7,
    research_context: str = "",
) -> str:
    """Generate a markdown prep plan and return it as a string."""
    weak_patterns = weak_patterns or []
    today = date.today().isoformat()
    interview_date = (date.today() + timedelta(days=days_until_interview)).isoformat()

    weak_section = "\n".join(f"- {p}" for p in weak_patterns) if weak_patterns else "None identified yet."

    # Cap research to ~4000 chars to stay within token rate limits.
    research_trimmed = research_context[:4000] + ("…" if len(research_context) > 4000 else "")
    research_section = (
        f"\n\n## Live research — real interview reports\n\n{research_trimmed}"
        f"\n\n**Important:** If the research above contains specific questions asked at "
        f"{company}, use those exact questions as drill material for the relevant rounds. "
        f"Do not substitute generic problems when real questions are available."
        if research_context
        else ""
    )

    user_msg = f"""Generate a prep plan for:

Company: {company}
Role: {role}
Round types: {", ".join(round_types)}
Days until interview: {days_until_interview} (interview date: {interview_date})
Today: {today}

Weak patterns to prioritise:
{weak_section}{research_section}
"""

    plan_md = await complete(
        messages=[{"role": "user", "content": user_msg}],
        system=_SYSTEM,
        model="claude-haiku-4-5-20251001",
        max_tokens=3000,
    )

    logger.info("generate_plan.done", interview_id=interview_id, company=company, rounds=round_types)
    return plan_md
