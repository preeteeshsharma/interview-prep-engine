from __future__ import annotations

import re
from datetime import date, timedelta

from app.integrations.llm_client import complete
from app.lib.logging import get_logger


async def _extract_confirmed_questions(research: str) -> list[str]:
    """Return a flat list of confirmed interview questions extracted from research."""
    if not research:
        return []
    result = await complete(
        messages=[{"role": "user", "content": (
            "Extract every confirmed interview question from this research. "
            "Return one question per line — no bullets, no numbering, no commentary.\n\n"
            f"{research}"
        )}],
        system="Extract only. One confirmed question per line. No commentary.",
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
    )
    return [line.strip() for line in result.strip().splitlines() if line.strip()]


def _assign_to_days(questions: list[str], days: int) -> list[list[str]]:
    """Distribute questions across days using round-robin so each day is balanced."""
    if not questions or days <= 0:
        return []
    buckets: list[list[str]] = [[] for _ in range(days)]
    for i, q in enumerate(questions):
        buckets[i % days].append(q)
    return [b for b in buckets if b]

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

**machine_coding** — Timed end-to-end implementation: working, runnable code in 60–90 min.
  Pick problems that match the company's domain:
  logistics/supply chain → Cab booking, Delivery slot allocator, Route optimizer
  infra/SaaS → Rate limiter, Task scheduler, Notification dispatcher
  consumer → Parking lot, Library management, Movie ticket booking, Food ordering

  Structure every machine coding session:
    Step 1 (~5 min): Read problem, list entities and key operations, ask clarifying questions
    Step 2 (~10 min): Design classes and interfaces on paper — no code yet
    Step 3 (~40 min): Implement core happy path; get it compiling and passing basic cases
    Step 4 (~15 min): Edge cases, error handling, concurrency considerations if asked
  Evaluation criteria: working code > clean code > extensibility. Ship first, refactor second.
  Total: ~60–90 min per problem.

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
**Interview:** {interview_date}
**Rounds:** {round_types}
**Generated:** {today}

---

## Day 1 — {focus_area}

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
- Cover every round type fully — do not skip or summarise drills to save space
- Spread drills across available days; front-load harder rounds (DSA, LLD, machine_coding, sysdesign)
- Schedule harder rounds (DSA, LLD, machine_coding, sysdesign) earlier in the plan
- Never exceed per-drill time limits: DSA 60 min, LLD 40 min, machine_coding 90 min,
  sysdesign 60 min, behavioral 20 min, hiring_manager 30 min
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

    research_section = (
        f"\n\n## Live research — real interview reports\n\n{research_context}"
        f"\n\n**Required:** Every confirmed question listed in the research above MUST appear "
        f"as a dedicated drill in the plan. Do not substitute or omit any confirmed question. "
        f"Generic problems may fill remaining days only after all confirmed questions are scheduled."
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

    # Pre-assign confirmed questions to days so coverage is deterministic.
    confirmed = await _extract_confirmed_questions(research_context)
    if confirmed:
        day_count = max(days_until_interview, 1)
        assignments = _assign_to_days(confirmed, day_count)
        schedule = "\n\n## Required day schedule — follow exactly\n" + "\n".join(
            f"Day {i + 1}: {' | '.join(qs)}" for i, qs in enumerate(assignments)
        )
        user_msg += schedule

    plan_md = await complete(
        messages=[{"role": "user", "content": user_msg}],
        system=_SYSTEM,
        model="claude-haiku-4-5-20251001",
        max_tokens=6000,
    )

    plan_md = _fix_header(plan_md, interview_date, today)
    logger.info("generate_plan.done", interview_id=interview_id, company=company, rounds=round_types)
    return plan_md


_SUPPLEMENT_SYSTEM = """You are an interview prep planner adding drills to an existing prep plan.

Given an existing plan and a list of net-new confirmed questions not yet covered,
generate ONLY the additional ## Day sections needed to cover those questions.
Follow the same drill format as the existing plan (Pattern/goal, Approach bullets, Time).
Number days starting from the next day after the last ## Day in the existing plan.
Output ONLY the new ## Day sections — no header, no metadata, no Weak areas section.
"""


async def generate_supplement(
    existing_plan: str,
    net_new_questions: list[str],
    merged_research: str,
    company: str,
    role: str,
    round_types: list[str],
    days_until_interview: int,
) -> str:
    """Generate drill sections for net-new questions to append to an existing plan."""
    questions_block = "\n".join(f"- {q}" for q in net_new_questions)
    user_msg = f"""Existing plan:
{existing_plan}

Net-new confirmed questions to add drills for (cover these only — do not repeat existing drills):
{questions_block}

Research context:
{merged_research}

Company: {company} | Role: {role} | Round types: {", ".join(round_types)}
Days until interview: {days_until_interview}
"""
    result = await complete(
        messages=[{"role": "user", "content": user_msg}],
        system=_SUPPLEMENT_SYSTEM,
        model="claude-haiku-4-5-20251001",
        max_tokens=3000,
    )
    logger.info("generate_supplement.done", company=company, net_new=len(net_new_questions))
    return result


def _fix_header(plan_md: str, interview_date: str, today: str) -> str:
    """Replace LLM-generated header date lines with Python-computed values.

    Haiku hallucinates past-year dates for 2026 timestamps (beyond training cutoff).
    Overwrite them unconditionally so the header is always correct.
    """
    plan_md = re.sub(r"\*\*Interview:\*\*.*", f"**Interview:** {interview_date}", plan_md, count=1)
    plan_md = re.sub(r"\*\*Generated:\*\*.*", f"**Generated:** {today}", plan_md, count=1)
    return plan_md
