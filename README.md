# interview-prep-engine

A WhatsApp-based interview prep bot. Forward an interview invite or text `prep`, and it researches the company, generates a day-by-day drill plan, and commits everything to a private GitHub vault. Mock interviews and Socratic study sessions run against that vault context.

---

## Commands

| Command | What it does |
|---|---|
| `prep Fivetran Senior SWE, may 12, dsa` | Research + plan straight to WhatsApp |
| `prep Google` | Asks for missing fields (date is required) |
| `prep google dsa june 15 refresh` | Regenerate plan even if one already exists |
| `mock google dsa` | Adversarial mock interview with vault context |
| `study google dsa` | Socratic study session from latest research + plan |
| `done google dsa hard` | Mark drill complete, rate difficulty |
| `done hard` | Shorthand when only one interview is active |
| `status` | List active interviews |
| `end` | End mock/study session, get Coach critique |

When a field is ambiguous (multiple active interviews, or missing company/round), the bot asks once and resolves on reply.

---

## How it works

**`prep`** — parses company, role, date, and rounds from free text. Runs a multi-source web search (Blind, Glassdoor, LeetCode Discuss, Reddit), generates a drill plan, and commits both to a private GitHub vault. One Interview row per `(company, round_type)` in the DB; the plan content lives in the vault.

**`mock`** — loads latest research + plan from the vault, opens an adversarial interview session. Each reply gets a next question from the Interviewer and a silent rubric score from the Observer. `end` triggers the Coach critique.

**`study`** — Socratic tutoring session using vault context. The tutor classifies each question (LeetCode / local build / bug squash) and gives hints on demand, never full solutions.

**Morning cron** — runs at 7am IST. Sends today's drill plan over WhatsApp, skips yesterday's uncompleted plan, bumps weak pattern weights for skipped drills.

---

## LLM routing

| Tier | Default | Fallback | Used for |
|---|---|---|---|
| Quality | Claude Sonnet 4.6 | Gemini 2.5 Pro | Researcher, Interviewer, Coach, Tutor |
| Fast | Gemini Flash 2.5 | Claude Haiku 4.5 | Parsing, classification, turn scoring |

Switch providers at runtime via the `app_config` table in Supabase — no redeploy needed.

---

## Setup

**Prerequisites:** Python 3.12+, [uv](https://github.com/astral-sh/uv), Twilio account, Anthropic API key, Supabase project, GitHub token + private vault repo.

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

# Optional: Vertex AI (enables Gemini)
GOOGLE_CLOUD_PROJECT=your-gcp-project
GOOGLE_CLOUD_LOCATION=us-central1
VERTEX_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
```

**Run locally:**

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
# expose via ngrok, set Twilio webhook to https://xxxx.ngrok.io/hooks/twilio
```

**Deploy to Fly.io:**

```bash
flyctl secrets set ANTHROPIC_API_KEY=... TWILIO_AUTH_TOKEN=... GITHUB_TOKEN=... DATABASE_URL=...
flyctl deploy
# update Twilio webhook to https://interview-prep-engine.fly.dev/hooks/twilio
```

---

## Cost (personal use)

| Service | Cost |
|---|---|
| Fly.io (shared-cpu-1x, 512MB) | ~$3–5/mo |
| Supabase | $0 (free tier) |
| Twilio WhatsApp Sandbox | $0 |
| Anthropic API | ~$2–5/mo |
| Vertex AI / Gemini | ~$0–2/mo |
| **Total** | **~$5–12/mo** |
