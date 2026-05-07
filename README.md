# interview-prep-engine

A deployed Python/FastAPI service that runs your interview prep loop via WhatsApp.

Three triggers:
- **Conversational `prep`** — send `prep Google senior backend june 15 dsa lld` (or just `prep Google`); the engine extracts what it can, asks once for anything missing, then researches and plans
- **7am daily cron** — sends today's drill nudge via WhatsApp
- **WhatsApp commands** — full mock interviews, Socratic study sessions, drill tracking

Multi-agent mock interviews: Interviewer (Sonnet 4.6, adversarial), Observer (Haiku 4.5, parallel rubric scoring), Coach (Sonnet 4.6, post-session critique). Researcher (Sonnet 4.6 + live web search) generates cited company/role research. Tutor (Sonnet 4.6) runs Socratic `study` sessions from the research.

---

## Architecture

```
┌─────────────────┐                ┌────────────────────────────────────────┐
│ Twilio WhatsApp │ ◄── outbound ──┤                                        │
│ Sandbox         │                │   interview-prep-engine                │
│                 │ ──── inbound ──►   (FastAPI / Python 3.12)              │
└─────────────────┘                │                                        │
                                   │  Agents                                │
┌─────────────────┐                │   Researcher  sonnet-4-6 + web_search  │
│ Anthropic API   │ ◄──────────────►   Interviewer sonnet-4-6 (adversarial) │
│                 │                │   Observer    haiku-4-5  (rubric)      │
│ web_search tool │                │   Coach       sonnet-4-6 (critique)    │
└─────────────────┘                │   Tutor       sonnet-4-6 (Socratic)    │
                                   │                                        │
┌─────────────────┐                │  Skills (loaded as system prompts)     │
│ Tavily Search   │ ◄──────────────►   interview_research.md                │
│ (primary)       │                │   interview_prep_assistant.md          │
└─────────────────┘                │   lld_problem_solving.md               │
                                   │                                        │
┌─────────────────┐                │  Tools                                 │
│ GitHub API      │ ◄── commits ───►   parse_prep_intent  (Haiku parser)    │
│ (prep-vault)    │                │   generate_plan                        │
└─────────────────┘                │   record_completion                    │
                                   │   research_company                     │
┌─────────────────┐                │                                        │
│ Supabase        │ ◄── state ─────►  interviews, prep_plans                │
│ (PostgreSQL)    │                │  mock_sessions, weak_patterns          │
└─────────────────┘                │  wa_window_state (+ pending_prep)      │
                                   │  outbound_idempotency                  │
                                   └────────────────────────────────────────┘
```

---

## WhatsApp commands

| Command | What it does |
|---|---|
| `prep Google` | Start conversational prep — engine asks for missing details |
| `prep Zapier senior backend june 15 dsa lld` | Full details in one message — goes straight to plan |
| `mock lld` | Start a mock interview (dsa / lld / sysdesign / behavioral) |
| `study` | Start a Socratic study session from latest research |
| `done hard` | Mark current drill complete and rate difficulty |
| `status` | List active interviews with rounds and scheduled date |
| `end` | End the current mock/study session and get Coach feedback |

### Conversational `prep` flow

If you omit any of role, interview date, or rounds, the engine asks once:

```
You: prep Google
Bot: Got it. Still need:
       • role (e.g. 'senior backend', 'L5 SWE')
       • interview date (e.g. 'june 15')
       • rounds (dsa / lld / sysdesign / behavioral / hiring_manager)

     Reply with the missing details (I'll use defaults if you skip).

You: L5 SWE, june 20, dsa lld sysdesign
Bot: Plan for Google (L5 SWE) on 2026-06-20: ...
```

Skip the follow-up reply and the engine uses defaults (role: software engineer, days: 7, rounds: dsa/lld/sysdesign/behavioral).

---

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) — `pip install uv`
- A [Twilio](https://www.twilio.com) account (free sandbox works)
- An [Anthropic](https://console.anthropic.com) API key
- A [Supabase](https://supabase.com) project (free tier works)
- A [Tavily](https://tavily.com) API key (free tier — used for web search in researcher)
- A GitHub personal access token with `repo` scope
- A **private** GitHub repo to use as your `prep-vault`

### 1. Clone and install

```bash
git clone https://github.com/preeteeshsharma/interview-prep-engine
cd interview-prep-engine
uv sync
```

### 2. Create your prep-vault repo

Create a **private** GitHub repo (e.g. `yourname/prep-vault`). The engine commits
prep plans and research reports as markdown — open it locally with Obsidian for a
searchable knowledge base.

### 3. Configure environment

```bash
cp .env.example .env
```

Fill in `.env`:

```env
# Anthropic — console.anthropic.com → API Keys
ANTHROPIC_API_KEY=sk-ant-...

# Twilio — console.twilio.com → Account Info
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_WHATSAPP=whatsapp:+14155238886   # Twilio sandbox number
TWILIO_TO_WHATSAPP=whatsapp:+91...           # your WhatsApp number

# Tavily — app.tavily.com → API Keys (free tier: 1000 req/month)
TAVILY_API_KEY=tvly-...

# GitHub — Settings → Developer settings → Personal access tokens (repo scope)
GITHUB_TOKEN=ghp_...
GITHUB_VAULT_REPO=yourname/prep-vault

# Supabase — project settings → Database → Connection string (Transaction pooler)
# Use the asyncpg format:
DATABASE_URL=postgresql+asyncpg://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres
```

### 4. Run locally

```bash
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Server starts on `http://localhost:8000`. Health check: `curl localhost:8000/health`

### 5. Expose webhooks for local dev

```bash
ngrok http 8000
```

Use the `https://xxxx.ngrok.io` URL for Twilio webhook configuration.

### 6. Connect Twilio WhatsApp Sandbox

1. Twilio Console → Messaging → Try it out → Send a WhatsApp message
2. Join the sandbox by sending the join code from your WhatsApp
3. Set the inbound webhook URL to `https://xxxx.ngrok.io/hooks/twilio`
4. Text `prep zapier` to test

---

## Deploy to Fly.io

```bash
flyctl launch --no-deploy   # first time only
flyctl secrets set ANTHROPIC_API_KEY=... TWILIO_AUTH_TOKEN=... # etc.
flyctl deploy
```

The `fly.toml` runs `alembic upgrade head` as a release command before starting the server.
After deploy: update your Twilio webhook URL to `https://interview-prep-engine.fly.dev/hooks/twilio`.

**Fly.io + Twilio note:** Fly terminates TLS internally, so requests arrive as `http://`.
Twilio signs with the public `https://` URL — the webhook handler corrects for this automatically.

---

## Mailgun (optional — for email-forwarded invites)

Mailgun free sandbox works for development. Key constraints:

- **Authorized recipients only** — add your email in the sandbox dashboard before testing
- **1 inbound route** — sufficient for this setup
- **100 emails/day** — plenty for personal use
- **24h log retention** — enough to grab Gmail verification codes

For production (forwarding from a real domain), upgrade to Foundation ($35/mo) or use a custom domain with Mailgun Flex.

---

## Project layout

```
app/
  agents/          # Researcher, Interviewer, Observer, Coach, Tutor, Orchestrator
  db/              # SQLAlchemy models (Supabase/PostgreSQL), async repos
  integrations/    # Anthropic, Twilio, GitHub clients; search/ (Tavily + fallback)
  jobs/            # morning_drill cron (APScheduler, 7am IST)
  lib/             # chunker, wa_window, idempotency, json_utils, logging
  routes/          # /hooks/twilio, /hooks/inbox, /health
  schemas/         # Pydantic models for agent I/O and webhooks
  skills/          # interview_research.md, interview_prep_assistant.md, lld_problem_solving.md
  tools/           # parse_prep_intent, generate_plan, record_completion, research_company
alembic/           # Async SQLAlchemy migrations
```

---

## Cost estimate (personal use)

| Service | Cost |
|---|---|
| Fly.io (shared-cpu-1x, 256MB) | ~$0–3/mo |
| Supabase (free tier) | $0 |
| Twilio WhatsApp Sandbox | $0 |
| Anthropic API | ~$2–5/mo (~4 mocks/week + prep plans) |
| Tavily (free tier) | $0 |
| GitHub API | $0 |
| **Total** | **~$2–8/mo** |
