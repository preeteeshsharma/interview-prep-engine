# interview-prep-engine

A deployed Python/FastAPI service that runs your interview prep loop via WhatsApp.

Three triggers:
- **7am daily cron** — generates today's drill, commits markdown to your private `prep-vault` GitHub repo, sends a WhatsApp nudge
- **Forwarded interview invite email** — parses company/role, classifies rounds, generates a calibrated prep plan
- **WhatsApp commands** — `prep <company>`, `mock <round>`, `done <rating>`, `status`

Multi-agent mock interviews: Interviewer (Sonnet, adversarial), Observer (Haiku, parallel rubric scoring), Coach (Sonnet, post-session critique with citation-grounded feedback). Reply `done hard` to mark a drill complete — the engine tracks weak areas and reassigns them more aggressively.

---

## Architecture

```
┌─────────────────┐                ┌────────────────────────────────────┐
│ Twilio WhatsApp │ ◄── outbound ──┤                                    │
│ Sandbox         │                │   interview-prep-engine            │
│                 │ ──── inbound ──►   (FastAPI / Python 3.12)          │
└─────────────────┘                │                                    │
                                   │  Triggers                          │
┌─────────────────┐                │   APScheduler  7am IST cron        │
│ Mailgun inbound │ ──── POST ─────►   POST /hooks/twilio               │
│ route           │                │   POST /hooks/inbox                │
└─────────────────┘                │                                    │
                                   │  Agents                            │
┌─────────────────┐                │   Interviewer  claude-sonnet-4-6   │
│ Anthropic API   │ ◄──────────────►   Observer     claude-haiku-4-5    │
└─────────────────┘                │   Coach        claude-sonnet-4-6   │
                                   │                                    │
┌─────────────────┐                │  Tools                             │
│ GitHub API      │ ◄── commits ───►   classify_rounds                  │
│ (prep-vault)    │                │   generate_plan                    │
└─────────────────┘                │   record_completion                │
                                   │                                    │
┌─────────────────┐                │  State                             │
│ SQLite (volume) │ ◄── state ─────►   interviews, prep_plans           │
└─────────────────┘                │   mock_sessions, weak_patterns     │
                                   │   wa_window_state, idempotency     │
                                   └────────────────────────────────────┘
```

---

## WhatsApp commands

| Command | What it does |
|---|---|
| `prep <company>` | Generate a prep plan for a company |
| `mock lld` | Start a mock interview (dsa / lld / sysdesign / behavioral) |
| `done hard` | Mark current drill complete and rate difficulty |
| `status` | List active interviews |
| `end` | End the current mock session and get Coach feedback |

---

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) — `pip install uv`
- A [Twilio](https://www.twilio.com) account (free sandbox works)
- An [Anthropic](https://console.anthropic.com) API key
- A [Mailgun](https://www.mailgun.com) account (free tier works)
- A GitHub personal access token with `repo` scope
- A **private** GitHub repo to use as your `prep-vault`

### 1. Clone and install

```bash
git clone https://github.com/preeteeshsharma/interview-prep-engine
cd interview-prep-engine
uv sync
```

### 2. Create your prep-vault repo

Create a **private** GitHub repo (e.g. `yourname/prep-vault`). This is where
the engine commits prep plans, drill completions, and mock transcripts as
markdown — open it locally with Obsidian for a searchable knowledge base.

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

# Mailgun — app.mailgun.com → Sending → Domain settings → Webhooks
MAILGUN_SIGNING_KEY=...

# GitHub — Settings → Developer settings → Personal access tokens (repo scope)
GITHUB_TOKEN=ghp_...
GITHUB_VAULT_REPO=yourname/prep-vault

# Database (default works for local dev; Railway sets this to a volume path)
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
```

### 4. Run locally

```bash
mkdir -p data
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Server starts on `http://localhost:8000`. Health check: `curl localhost:8000/health`

### 5. Expose webhooks for local dev

```bash
ngrok http 8000
```

Use the `https://xxxx.ngrok.io` URL for Twilio and Mailgun webhook configuration.

### 6. Connect Twilio WhatsApp Sandbox

1. Twilio Console → Messaging → Try it out → Send a WhatsApp message
2. Join the sandbox by sending the join code from your WhatsApp
3. Set the inbound webhook URL to `https://xxxx.ngrok.io/hooks/twilio`
4. Text `prep zapier` to test

### 7. Configure Mailgun inbound route

1. Mailgun → Receiving → Create Route
2. Match: `match_recipient("prep@yourdomain.mailgun.org")`
3. Action: Forward to `https://xxxx.ngrok.io/hooks/inbox`
4. Forward an interview invite email to `prep@yourdomain.mailgun.org` to test

---

## Deploy to Railway

```bash
railway login
railway init
railway up
```

Set all `.env` variables as Railway environment variables. Set `DATABASE_URL`
to use the Railway volume mount path:

```
DATABASE_URL=sqlite+aiosqlite:////data/app.db
```

Add a persistent volume mounted at `/data` so the SQLite database survives
redeploys.

After deploy: update your Twilio and Mailgun webhook URLs to the Railway
public URL.

---

## Run evals

```bash
uv run python evals/run.py
```

Runs the 3-JD golden set (Zapier, Stripe, CRED) against `classify_rounds`.
CI runs this on every push via `.github/workflows/eval.yml`.

---

## Project layout

```
app/
  agents/          # Interviewer, Observer, Coach, Orchestrator
  db/              # SQLAlchemy models, async repos
  integrations/    # Anthropic, Twilio, GitHub clients
  jobs/            # morning_drill cron
  lib/             # chunker, wa_window, idempotency, logging
  routes/          # /hooks/twilio, /hooks/inbox, /health
  schemas/         # Pydantic models for agent I/O and webhooks
  tools/           # classify_rounds, generate_plan, record_completion
evals/             # Golden JD fixtures + eval runner
tests/             # Unit tests
```

---

## Cost estimate (personal use)

| Service | Cost |
|---|---|
| Railway Hobby | ~$0–3/mo |
| Twilio WhatsApp Sandbox | $0 |
| Anthropic API | ~$2–4/mo (cron + ~4 mocks/week, with prompt caching) |
| GitHub API | $0 |
| Mailgun (first 100 emails free) | ~$0 |
| **Total** | **~$2–7/mo** |

---

## Iteration log

See [ITERATIONS.md](ITERATIONS.md) for the real bugs hit during development
and the structural fixes that resolved them.
