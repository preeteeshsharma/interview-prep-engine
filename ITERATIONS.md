# Iterations

Real bugs hit during development. Each became a structural fix.

---

## V1 — Multi-agent serial latency made mocks unusable

**Problem:** First implementation ran Interviewer → wait → Observer → wait.
WhatsApp turns took 8–12 seconds. Unusable in a conversational context.

**Fix:** `asyncio.gather(interviewer.next_turn(), observer.score())` in
`orchestrator.run_turn()`. Observer scores the transcript in parallel with
the Interviewer generating the next question. Observer result is persisted
silently — it never touches user-visible latency. Coach still runs serially
post-session (it needs the full transcript).

**File:** `app/agents/orchestrator.py` → `run_turn()`

---

## V2 — Coach hallucinated transcript quotes

**Problem:** Without enforcement, Coach paraphrased or invented quotes.
Soft prompts asking it to "quote the transcript" did not work — it would
fabricate plausible-sounding candidate statements.

**Fix:** Pydantic `Critique` model requires `quote_offset: int` (0-indexed
transcript turn index). Orchestrator validates every offset is within
`range(len(transcript))` and rejects the response with an error message on
failure. Retries once with the validation error fed back into the prompt.
Only valid entries are stored; invalid entries are dropped rather than crashing.

**File:** `app/agents/coach.py` → `critique()`, `app/schemas/agent_io.py`

---

## V3 — Outbound failed silently after 24h WhatsApp window closed

**Problem:** WhatsApp's 24-hour rule: free-form messages only allowed within
24h of the last user inbound. Cron-initiated messages sent outside this window
were silently rejected by Twilio with no error raised.

**Fix:** `wa_window_state` table tracks `last_inbound_at` per recipient.
Morning drill checks `WaWindowRepository.is_within_window()` before sending.
Outside the window it falls back to a short nudge (Twilio Sandbox accepts
freeform; production would use an approved template SID).

**File:** `app/jobs/morning_drill.py`, `app/db/repos/wa_window.py`

---

## V4 — Cron duplicate fired on Railway redeploy

**Problem:** Mid-cycle Railway redeploy caused two `morning_drill` invocations
within 30 seconds. Two duplicate WhatsApp messages went out for the same drill.

**Fix:** Outbound idempotency key = `SHA256(date + recipient + interview_id)`.
Checked before sending; written after a successful send. Duplicate runs skip
the send entirely. UNIQUE constraint on `outbound_idempotency.idempotency_key`
prevents races at the DB layer.

**File:** `app/jobs/morning_drill.py`, `app/db/repos/outbound_idempotency.py`,
`app/lib/idempotency.py`

---

## V5 — Engine reassigned drills already completed

**Problem:** No completion signal meant the cron kept generating plans for
problems already done. Weak areas got no extra weight; strong areas weren't
skipped.

**Fix:** WhatsApp `done easy/medium/hard` reply handler marks
`prep_plans.completed_at` and `self_rating`. Hard-rated drills bump
`weak_patterns.weight` by 1.5; medium by 0.5. Skipped plans (no reply by
next morning) bump by 2.0. `generate_plan` receives the top weak patterns
and recent completed drill names; the system prompt tells Claude to
prioritise weak areas and avoid recently completed problems.

**File:** `app/tools/record_completion.py`, `app/jobs/morning_drill.py`,
`app/tools/generate_plan.py`

---

## V6 — Token cost on long mock sessions

**Problem:** A 30-minute behavioral mock with all-Sonnet agents cost ~$0.40.
Observer runs on every turn — over 10 turns that adds up.

**Fix:** Observer downgraded to `claude-haiku-4-5-20251001`. Rubric scoring
is a simpler cognitive task (1–5 scores on five dimensions) that doesn't
need Sonnet's reasoning depth. Cost drops ~60% with no measurable rubric
quality regression on spot checks.

**File:** `app/agents/observer.py`
