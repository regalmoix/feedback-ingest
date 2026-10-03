# Phase 6: Hardening and interview pack

Status: historical design record.

Status: implemented 2026-10-03 (commits 63883ad, d77cc76, 9d6a649, cadea41); review fixes applied after.

**Update after the second review round (commit cbb788c).** This is the design as written; the code wins. Built differently:
- The log format adds `attempts` to the keys, and `\r` and `\n` in messages are escaped. Worker and pipeline lines carry `raw_event_id`; pull lines carry `tenant_id` and `source_id`; startup lines show "-".
- `/health` has no `uptime_seconds`, `processed_total` or `dead_total` counters. It shows global queue counts, worker and scheduler flags, and `failing_sources` (a count).
- `GET /admin/raw-events` filters by `status` and `limit` only. Replay by source is bulk replay, `POST /admin/raw-events/replay?source_id=&status=&limit=`; there is no time-window filter.
- No `Dockerfile` was added.

## What this phase builds, in one paragraph

Nothing new for the system to do; everything the user needs to run it, break it and explain it. Structured
logs with correlation ids, a health endpoint that doubles as the firefight dashboard, a README that gets a
stranger from clone to demo in three commands, and the interview pack: a whiteboard script, a question bank, a
failure-scenario table, a firefight runbook, an alternatives sheet, an extensions sheet, a glossary, and a short
slide deck. Then one last review pass over the whole repository.

## Code (small, all optional polish)
- `main.py` logging: one stream handler, format
  `%(asctime)s %(levelname)s %(name)s %(message)s raw_event_id=%(raw_event_id)s tenant_id=%(tenant_id)s source_id=%(source_id)s`
  with a `logging.Filter` that defaults missing keys to `-`. Pipeline, worker, pull and scheduler log with `extra=`.
- `/health` adds `uptime_seconds`, `processed_total`, `dead_total` counters kept in-process by the pipeline
  (plain ints behind a lock; `# ponytail: process-local counters; Prometheus client when there is a scraper`).
- `GET /admin/raw-events` gains `source_id` and `since` filters (replay by tenant/source/window = list + loop).
- `Dockerfile` (≤12 lines, `uv sync --frozen`, `uvicorn`) only if everything else is done.

## Interview pack (`docs/interview/`), each file short, plain, and sayable aloud
- `whiteboard.md`: the 10-minute script. What to draw first (one payload's journey: webhook → raw_events →
  worker → connector → feedback_records → query), then the second entry (pull), then the three guarantees
  (durable before ack, idempotent upsert, replay from raw). A box list of the actual module names so the
  drawing matches the repo. Ends with "the one sentence".
- `qa_bank.md`: ~40 questions, each with a 2-sentence answer and a "go deeper" paragraph. Grouped: design
  choices, failure modes, scale, security, data model, extensibility, process ("did you write this?", answered
  honestly: designed and reviewed with AI agents, every decision council-reviewed, every file read by the user).
- `failure_scenarios.md`: table of component down → symptom → what this code does today → what prod adds.
  Covers every item in PLAN.md "Interview prep coverage" plus the council's additions (noisy tenant, uvicorn
  --workers N, slow transform blocking, PII retention, cursor on crash, out-of-order edits, delete-then-replay).
- `firefight_runbook.md`: "client says Playstore reviews missing since yesterday" as numbered steps with the
  exact curl for each (health → queue counts → dead list → raw event payload → replay or manual sync →
  verification query → comms template with timestamps).
- `alternatives.md`: every rejected option from ADR-001..003 and PLAN.md in one table: option, why not now,
  when it becomes right.
- `extensions.md`: add a source (5 steps, file names), Postgres swap (set `FI_DATABASE_URL`, add a driver, change three queries (claim, upsert, enqueue), add migrations), Kafka/SQS
  swap (which adapter, what changes in retry semantics), horizontal workers, per-tenant fairness, enrichment
  stage (language, sentiment), tombstone/GDPR erasure, backfill, shadow-run a new connector version.
- `glossary.md`: inbox/durable log, lease, fence, tombstone, idempotency vs dedupe, cursor, overlap window,
  dead letter, replay, HMAC, port, adapter, Protocol, contract test, full-snapshot rule, connector version.
- `debt_ledger.md`: output of `ponytail:ponytail-debt` (every `# ponytail:` marker with its ceiling), framed
  as "what I would do next and why I didn't yet".
- `demo_script.md`: the `demo.sh` steps with what to say at each one and what the interviewer sees.

## Architecture doc final (`docs/00_architecture.md`)
Mermaid diagrams: component diagram; push sequence; pull sequence; raw-event state machine
(pending → processing → processed | failed → pending | dead → pending via replay); tenancy diagram (key → tenant
→ sources → records). Keep the ASCII diagram for whiteboard fidelity.

## Slides (`docs/slides/deck.pptx`, built by an Opus agent with `anthropic-skills:pptx`, local file only)
10 slides: problem, requirements map, architecture, one payload's journey, data model, idempotency and
replay, failure handling, extensibility (add Zendesk), what I'd do next, demo. Content lifted from the docs.

## README
Three commands to run, three to demo, the design in ten lines, links to every doc, and the "status of
requirements" table (Must / Good-to-have → where it is implemented → which test proves it).

## Final review
Full reviewer fleet over the whole repo (code-reviewer, silent-failure-hunter, ponytail-audit,
pr-test-analyzer) → fix agent → gates green → commit "Phase 6".

## How to explain this phase in the interview
It is the phase that makes the rest explainable. Nothing here changes behaviour.
