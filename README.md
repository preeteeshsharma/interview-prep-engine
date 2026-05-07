# interview-prep-engine

A WhatsApp-based interview prep bot. You text it, it researches the company using live web search, generates a day-by-day plan, runs adversarial mock interviews, and commits everything to a private GitHub vault.

---

## What actually happens when you send `prep Fivetran Senior SWE, may 12, dsa`

```
1. parse_prep_intent (Haiku)
   → extracts company=Fivetran, role=Senior SWE, date=2026-05-12, rounds=[dsa]
   → "Coding Ability and Problem Solving" also works — mapped to dsa in Python

2. researcher (Sonnet + Anthropic web_search)
   → runs 4-6 searches across Blind, LeetCode Discuss, Glassdoor, Reddit
   → guided by interview_research.md skill loaded as its system prompt
   → returns a sourced report with per-question citations and a sources table
   → single round specified → questions mode (actual Qs asked, not full loop)

3. generate_plan (Haiku)
   → takes the research + round types + days until interview
   → guided by the plan system prompt (company-specific drills, LeetCode numbers)
   → if research contains real questions, uses those as drill material

4. DB write: Interview + PrepPlan rows in Supabase

5. Vault commit: plan + research saved as markdown to prep-vault GitHub repo

6. WhatsApp reply: first 1200 chars of plan + "(Full plan + sources in prep-vault)"
```

---

## What actually happens when you send `mock dsa`

```
1. Creates MockSession row in DB

2. Interviewer (Sonnet) opens with a question
   → system prompt = _ROUND_PROMPTS["dsa"] — Socratic hint ladder, never gives answer
   → for lld: enforces 5-phase HelloInterview framework from lld_problem_solving.md

3. Each reply triggers two parallel calls:
   a. Interviewer (Sonnet) — next adversarial question
   b. Observer (Haiku) — scores the turn against a rubric silently

4. When you text "end":
   → Coach (Sonnet) reads full transcript + Observer scores
   → returns post-session critique with specific citations from your answers
   → MockSession finalized in DB
```

---

## What actually happens when you send `study`

```
1. Reads latest research file from prep-vault GitHub repo

2. Tutor (Sonnet) opens the session
   → system prompt = interview_prep_assistant.md skill
   → lists all questions from research, classifies each:
     [LeetCode] — known platform problem
     [Local]    — build it on your machine
     [Bug Squash] — fix bugs in a given codebase
   → asks which one to start with

3. Each reply: Tutor gives the next smallest useful hint (Socratic)
   → never gives a complete solution unprompted
   → hint ladder: question → pattern name → skeleton → explanation
```

---

## How skills work

The three `.md` files in `app/skills/` are **not prompt templates** — they are the full skill content from Claude's built-in skills, loaded as the system prompt for each agent at runtime:

| Skill file | Used by | What it does |
|---|---|---|
| `interview_research.md` | Researcher | Directs multi-source search strategy, output format with citations |
| `interview_prep_assistant.md` | Tutor | Socratic tutoring flow, question classification, hint ladder |
| `lld_problem_solving.md` | Interviewer (lld) | 5-phase HelloInterview framework, SOLID enforcement |

The agent receives the skill as its system prompt and a minimal task description as the user message — e.g. `"Research the Fivetran Senior SWE interview process — process mode."` The skill then drives the search planning and output format itself.

---

## Model choices and why

| Agent | Model | Reason |
|---|---|---|
| Researcher | Sonnet 4.6 | Needs strong reasoning to plan searches, synthesize across sources, write citations |
| Interviewer | Sonnet 4.6 | Adversarial probing requires nuanced follow-up; must track what candidate hasn't addressed |
| Coach | Sonnet 4.6 | Post-session critique needs to cite specific transcript moments |
| Tutor | Sonnet 4.6 | Socratic flow requires judging how much hint to give at each step |
| Observer | Haiku 4.5 | Rubric scoring is classification — fast and cheap, runs in parallel with Interviewer |
| parse_prep_intent | Haiku 4.5 | Simple extraction task; Sonnet overkill and wastes token quota |
| generate_plan | Haiku 4.5 | Structured formatting against a template — no complex reasoning needed |

---

## Web search

The researcher uses **Anthropic's built-in `web_search_20250305` tool** — included in the API, no external service needed. The model calls it multiple times per research run (guided by the skill's Step 2 search strategy).

There is no Tavily dependency in the active code path. The `app/integrations/search/` directory contains an unused abstraction layer that was built before Anthropic's native search tool was available — it can be deleted.

---

## Rate limits (Tier 1 — 30k Sonnet input tokens/min)

The researcher + web_search is the heavy consumer: each search round-trip feeds results back to the model as input tokens. With 4-6 searches, a single research run can consume 20-25k tokens.

Mitigations in place:
- Research context capped at 4000 chars before passing to generate_plan
- generate_plan uses Haiku (separate rate limit bucket, 50k/min)
- 429 retry waits 65s (per-minute limit needs >60s to reset; 2s retry is useless)

Upgrading to Tier 2 (spend $5 real money on the API — credit grants don't count) raises Sonnet input to 160k/min and eliminates the constraint.

---

## WhatsApp commands

| Command | What it does |
|---|---|
| `prep Fivetran Senior SWE, may 12, dsa` | Full details — straight to plan |
| `prep Google` | Conversational — asks once for missing fields |
| `prep Zapier SWE, june 15, Coding Ability and Problem Solving` | Actual round name works, mapped to dsa |
| `mock dsa` | Start mock (dsa / lld / sysdesign / behavioral) |
| `study` | Socratic session from latest research |
| `done hard` | Mark drill complete (easy / medium / hard) |
| `status` | List active interviews |
| `end` | End mock/study session, get Coach critique |

### Conversational prep flow

If details are missing, the engine asks once and proceeds with defaults on the follow-up:

```
You:  prep Google
Bot:  Got it. Still need:
        • role (e.g. 'senior backend', 'L5 SWE')
        • interview date (e.g. 'june 15')
        • rounds (dsa / lld / sysdesign / behavioral / hiring_manager)
      Reply with the missing details (I'll use defaults if you skip).

You:  L5 SWE, june 20, dsa lld sysdesign
Bot:  Plan for Google (L5 SWE) on 2026-06-20: ...
```

Defaults if you skip the follow-up: role=software engineer, days=7, rounds=dsa/lld/sysdesign/behavioral.

Pending state is stored in `WaWindowState.pending_prep` (Supabase). A new command clears it.

---

## State model

| Table | What's in it |
|---|---|
| `interviews` | company, role, round_types, scheduled_for, status |
| `prep_plans` | plan_md, time_budget_min, completed_at, self_rating, skipped |
| `mock_sessions` | round_type, transcript_json, rubric_json, critique_json |
| `weak_patterns` | pattern, weight — drives drill reassignment |
| `wa_window_state` | last_inbound_at, last_template_at, pending_prep (mid-conversation state) |
| `outbound_idempotency` | prevents duplicate WhatsApp sends |

---

## Setup

### Prerequisites

- Python 3.12+, [uv](https://github.com/astral-sh/uv)
- Twilio account (free sandbox)
- Anthropic API key (paid account — credit grants alone stay on Tier 1)
- Supabase project (free tier)
- GitHub personal access token (`repo` scope) + private vault repo

### Environment

```env
ANTHROPIC_API_KEY=sk-ant-...

TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_WHATSAPP=whatsapp:+14155238886
TWILIO_TO_WHATSAPP=whatsapp:+91...

GITHUB_TOKEN=ghp_...
GITHUB_VAULT_REPO=yourname/prep-vault

# Supabase transaction pooler — asyncpg format
DATABASE_URL=postgresql+asyncpg://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres
```

No Tavily key needed — web search is Anthropic's built-in tool.

### Run locally

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
# expose: ngrok http 8000
# set Twilio webhook to https://xxxx.ngrok.io/hooks/twilio
```

### Deploy

```bash
flyctl secrets set ANTHROPIC_API_KEY=... TWILIO_AUTH_TOKEN=... GITHUB_TOKEN=... DATABASE_URL=...
flyctl deploy
# update Twilio webhook to https://interview-prep-engine.fly.dev/hooks/twilio
```

Fly terminates TLS internally — Twilio signs with `https://` but forwards as `http://`. The webhook handler corrects for this automatically before HMAC validation.

---

## Cost (personal use)

| Service | Cost |
|---|---|
| Fly.io (shared-cpu-1x, 256MB) | ~$0–3/mo |
| Supabase | $0 (free tier) |
| Twilio WhatsApp Sandbox | $0 |
| Anthropic API | ~$2–5/mo (researcher is the main cost) |
| GitHub API | $0 |
| **Total** | **~$2–8/mo** |
