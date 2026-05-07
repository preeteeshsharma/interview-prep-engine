# interview-prep-engine

A WhatsApp-based interview prep bot. You text it, it researches the company using live web search, generates a day-by-day plan, runs adversarial mock interviews, and commits everything to a private GitHub vault.

---

## What actually happens when you send `prep Fivetran Senior SWE, may 12, dsa`

```
1. parse_prep_intent (fast tier — Gemini Flash or Haiku)
   → extracts company=Fivetran, role=Senior SWE, date=2026-05-12, rounds=[DSA]
   → "Coding Ability and Problem Solving" also works — mapped to DSA in Python

2. researcher (quality tier — Claude Sonnet + web_search)
   → runs 4-6 searches across Blind, LeetCode Discuss, Glassdoor, Reddit
   → guided by interview_research.md skill loaded as its system prompt
   → returns a sourced report with per-question citations and a sources table
   → single round specified → questions mode (actual Qs asked, not full loop)

3. generate_plan (fast tier — Gemini Flash or Haiku)
   → takes the research + round types + days until interview
   → guided by the plan system prompt (company-specific drills, LeetCode numbers)
   → if research contains real questions, uses those as drill material

4. DB write: Interview + PrepPlan rows in Supabase

5. Vault commit: two files per run in prep-vault GitHub repo
   → fivetran/dsa/{epoch}-plan.md
   → fivetran/dsa/{epoch}-research.md
   (epoch suffix means no overwriting — every run creates new files)

6. WhatsApp reply: first 1200 chars of plan + "(Full plan + sources in prep-vault)"
```

---

## What actually happens when you send `mock google dsa`

```
1. Loads vault context for google/dsa/ — latest research.md + latest plan.md
   (picked independently by epoch — if one failed, you still get the best of each)

2. Creates MockSession row in DB

3. Interviewer (Sonnet) opens with a question
   → system prompt = _ROUND_PROMPTS["dsa"] — Socratic hint ladder, never gives answer
   → for lld: enforces 5-phase HelloInterview framework from lld_problem_solving.md
   → vault context injected: real questions asked at Google + candidate's prep plan

4. Each reply triggers two parallel calls:
   a. Interviewer (Sonnet) — next adversarial question
   b. Observer (fast tier) — scores the turn against a rubric silently

5. When you text "end":
   → Coach (Sonnet) reads full transcript + Observer scores
   → returns post-session critique with specific citations from your answers
   → MockSession finalized in DB
```

---

## What actually happens when you send `study google dsa`

```
1. Loads vault context for google/dsa/
   → latest *-research.md (by epoch) — questions, sources, themes
   → latest *-plan.md (by epoch) — day-by-day drills, assigned LeetCode problems
   Both picked independently — no need to re-run prep

2. Tutor (Sonnet) opens the session with both files as context
   → system prompt = interview_prep_assistant.md skill
   → lists all questions from research, classifies each:
     [LeetCode] — known platform problem
     [Local]    — build it on your machine
     [Bug Squash] — fix bugs in a given codebase
   → references assigned problems from the plan
   → asks which one to start with

3. Each reply: Tutor gives the next smallest useful hint (Socratic)
   → never gives a complete solution unprompted
   → hint ladder: question → pattern name → skeleton → explanation
```

---

## LLM provider routing

Two tiers. Provider for each tier is runtime-configurable via the `app_config` table in Supabase — no redeploy needed.

| Tier | Default primary | Fallback | Used for |
|---|---|---|---|
| Quality (`complete`) | Claude Sonnet 4.6 | Gemini 2.5 Pro | Researcher, Interviewer, Coach, Tutor |
| Fast (`complete_fast`) | Gemini Flash 2.5 | Claude Haiku 4.5 | Parsing, classification, scoring |

To switch providers at runtime:

```sql
-- Supabase SQL editor — takes effect within 60s (TTL cache)
UPDATE app_config SET value = 'gemini'    WHERE key = 'llm.primary_provider';
UPDATE app_config SET value = 'anthropic' WHERE key = 'llm.fast_provider';
```

Valid values: `'anthropic'` | `'gemini'`. A CHECK constraint on the table rejects anything else.

---

## How skills work

The three `.md` files in `app/skills/` are **not prompt templates** — they are full skill content loaded as the system prompt for each agent at runtime:

| Skill file | Used by | What it does |
|---|---|---|
| `interview_research.md` | Researcher | Multi-source search strategy, citation format, no URL fabrication |
| `interview_prep_assistant.md` | Tutor | Socratic tutoring flow, question classification, hint ladder |
| `lld_problem_solving.md` | Interviewer (lld) | 5-phase HelloInterview framework, SOLID enforcement |

---

## WhatsApp commands

| Command | What it does |
|---|---|
| `prep Fivetran Senior SWE, may 12, dsa` | Full details — straight to plan |
| `prep Google` | Conversational — asks once for missing fields |
| `prep Zapier SWE, june 15, Coding Ability and Problem Solving` | Actual round name from invite works, mapped to DSA |
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

Defaults if you skip the follow-up: role=software engineer, days=7, rounds=DSA/LLD/sysdesign/behavioral.

Pending state is stored in `WaWindowState.pending_prep` (Supabase). A new command clears it.

---

## State model

| Table | What's in it |
|---|---|
| `interviews` | company, role, round_types (`["DSA", "LLD", ...]`), scheduled_for, status |
| `prep_plans` | plan_md, time_budget_min, completed_at, self_rating, skipped |
| `mock_sessions` | round_type, transcript_json, rubric_json, critique_json |
| `weak_patterns` | pattern, weight — drives drill reassignment |
| `wa_window_state` | last_inbound_at, last_template_at, pending_prep (mid-conversation state) |
| `app_config` | key/value runtime config (llm.primary_provider, llm.fast_provider) |
| `outbound_idempotency` | prevents duplicate WhatsApp sends |

---

## Vault structure

Each prep run writes two files under `{company-slug}/{round-slug}/{epoch}-*.md`:

```
prep-vault/
  fivetran/
    dsa/
      1778165199-plan.md
      1778165199-research.md
      1778200000-plan.md      ← second run, new epoch, no overwrite
      1778200000-research.md
  google/
    lld/
      1778300000-plan.md
      1778300000-research.md
```

`study` picks the file with the largest epoch (most recent) automatically.

---

## Web search

The researcher uses **Anthropic's built-in `web_search_20250305` tool** — included in the API, no external service needed. Gemini falls back to `google_search` when used as the quality-tier provider.

---

## Rate limits (Tier 1 — 30k Sonnet input tokens/min)

The researcher + web_search is the heavy consumer: 4-6 searches can consume 20-25k tokens per run.

Mitigations in place:
- Research context capped at 4000 chars before passing to generate_plan
- generate_plan uses fast tier (Gemini Flash or Haiku — separate quota)
- 429 retry waits 65s (per-minute limit needs >60s to reset)

Upgrading to Tier 2 (spend $5 real money on the API — credit grants don't count) raises Sonnet input to 160k/min.

---

## Setup

### Prerequisites

- Python 3.12+, [uv](https://github.com/astral-sh/uv)
- Twilio account (free sandbox)
- Anthropic API key
- Supabase project (free tier)
- GitHub personal access token (`repo` scope) + private vault repo
- Google Cloud project with Vertex AI enabled *(optional — for Gemini)*

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

# Optional: Vertex AI (enables Gemini as quality/fast tier)
GOOGLE_CLOUD_PROJECT=your-gcp-project
GOOGLE_CLOUD_LOCATION=us-central1
VERTEX_SERVICE_ACCOUNT_JSON={"type":"service_account",...}  # full JSON on one line
```

If `GOOGLE_CLOUD_PROJECT` is not set, both tiers fall back to Anthropic (Sonnet for quality, Haiku for fast).

### Run locally

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
# expose: ngrok http 8000
# set Twilio webhook to https://xxxx.ngrok.io/hooks/twilio
```

### Deploy to Fly.io

```bash
flyctl secrets set ANTHROPIC_API_KEY=... TWILIO_AUTH_TOKEN=... GITHUB_TOKEN=... DATABASE_URL=...
# Optional Vertex AI secrets:
flyctl secrets set GOOGLE_CLOUD_PROJECT=... VERTEX_SERVICE_ACCOUNT_JSON='{"type":...}'
flyctl deploy
# update Twilio webhook to https://interview-prep-engine.fly.dev/hooks/twilio
```

Fly terminates TLS internally — the webhook handler reconstructs the `https://` URL before Twilio HMAC validation.

---

## Cost (personal use)

| Service | Cost |
|---|---|
| Fly.io (shared-cpu-1x, 512MB) | ~$3–5/mo |
| Supabase | $0 (free tier) |
| Twilio WhatsApp Sandbox | $0 |
| Anthropic API | ~$2–5/mo (researcher is the main cost) |
| Vertex AI / Gemini | ~$0–2/mo (fast tier calls are cheap) |
| GitHub API | $0 |
| **Total** | **~$5–12/mo** |
