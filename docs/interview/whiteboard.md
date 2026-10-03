# Whiteboard script (10 minutes)

Terms: [glossary.md](glossary.md). Follow-up answers: [qa_bank.md](qa_bank.md). The live run that matches this
drawing: [demo_script.md](demo_script.md).

Draw in this order. Each step is one box or arrow and one sentence. Module names in brackets are the real
files, so if someone opens the repo the drawing matches.

> **Five things to know before you walk in**
>
> 1. **The pull cursor moves only on the final page** of a window. `start_after` is read only while the
>    cursor is null. A backfill means resetting the cursor (by hand in SQL today) and, if a day is busy,
>    lowering `window_days` with `PATCH /v1/sources/{id}`. Duplicates on every sync are normal: the cursor
>    keeps a 60 s overlap and `before:` is day-granular, and the unique key drops the repeats.
> 2. **Attempts are counted by the claim**, not by the failure. A replayed event resets to 0 and the next claim
>    makes it 1, so it shows `attempts` 1; the cap check is `attempts > FI_MAX_ATTEMPTS`.
> 3. **`/health` goes 503** if a thread is dead, if storage is down, or if the worker makes no progress for
>    `max(3 × FI_WORKER_POLL_SECONDS, 10)` seconds.
> 4. **The version guard is Python `merge()` under `BEGIN IMMEDIATE`**; SQL `ON CONFLICT` is the Postgres form.
>    `SKIP LOCKED` does not run today. The per-source sync lock is per process, so `uvicorn --workers N` can
>    poll Discourse twice (failure_scenarios, "`uvicorn --workers N`").
> 5. **Say it first:** the Play Store push is a stand-in (Google has no review webhook; reviews are polled), and
>    Twitter's CRC handshake is not built.
>
> Live change for the authorship question: add a field to `PlaystoreMetadata` in
> `feedback_ingest/domain/metadata.py` and run `uv run pytest tests/unit/connectors -q`.

## 0. The one sentence (say it before drawing anything)

"We save the raw payload to disk before we say yes. Everything after that is a retry or a replay."

If they want the bigger picture first: "Enterpret's public site describes three stages: Unify, Understand,
Act. This service is the Unify stage. It takes feedback from many sources and turns it into one shape, a
Feedback Record. Understand (the taxonomy of themes and keywords, and Wisdom, the question-and-answer tool)
reads those records later. Act (Slack, Jira and so on) comes after that. We build none of the later stages."

## 1. Two doors in, one pipe (2 minutes)

Draw a box on the left: **Source** (Intercom, Playstore, Twitter, Discourse, and a custom webhook). Two arrows
out of it.

- Arrow 1, **push**: `POST /v1/sources/{id}/events` [api/ingest.py]. Say: "The webhook does two checks and one
  write. First, the source id in the URL picks the source; it is long and unguessable. Second, the signature
  must be right: an HMAC over the raw bytes with that source's own secret. No API key, because a real sender
  cannot add ours; the tenant comes from the source row. Then one insert, then 202. 202 means accepted, not
  processed." Only push sources take webhooks: a pull source answers 409. Any body over 1 MiB gets
  413.
- Arrow 2, **pull**: `POST /v1/sources/{id}/sync` or the scheduler tick [api/sync.py, services/scheduler.py,
  services/pull.py]. Say: "Polling is just another producer. The connector returns pages; every payload goes
  through the same accept call a webhook uses." One sync per source at a time: a second sync of the same
  source while one runs gets 409.

Both arrows land on one box: **`IngestionService.accept`** [services/ingestion.py]. Under it draw the table:
**`raw_events`** with columns `status, attempts, next_attempt_at, lease_until, external_event_id`
[adapters/sqlalchemy/raw_event_queue.py]. Say: "This table is both the audit log and the work queue. Unique on
(source, external event id), so a repeated webhook is stored once."

If asked "why not a real queue": "A table I can query, replay by id and filter per tenant. It is one process
and zero infrastructure for a demo. The adapter boundary is where Kafka or SQS would go, and I would be honest
that a broker changes the retry model, not just the adapter."

## 2. The engine (2 minutes)

Draw a box to the right of the table: **Worker thread** [services/worker.py]. Arrow from the table labelled
"claim with lease". Say: "One SQL statement claims a batch of rows: rows that are pending or failed and due
now, or rows whose lease expired. It sets them to processing with a lease and returns them. Atomic, so two
workers never take the same row. A crashed worker's rows come back when the lease expires."

Below the worker: **`PipelineService.process`** [services/pipeline.py]. Three outcomes, draw three arrows back
to the table:
- processed
- failed, with `next_attempt_at = now + 2^attempts` (capped), retried later
- dead after max attempts, or immediately for a bad payload (validation error)

Say: "Bad payloads die on the first try. They are never retried. Flaky things back off. Marks are fenced on
the lease, so a stale worker cannot overwrite a newer claim."

## 3. The translation (2 minutes)

Between the pipeline and the records table draw: **`CONNECTORS[source.type]`** [connectors/registry.py] with
five small boxes: discourse, playstore, twitter, intercom, custom [connectors/*.py]. Say: "A connector
validates the payload with a Pydantic input model, then maps it to our record. Nothing else in the system
knows which sources exist."

Point at the custom box. Say: "This one takes the batch shape Enterpret's public webhook docs describe:
`{"records": [...]}`, each with an `id`, a `type` and `createdAt` in epoch seconds. One push is one raw event,
and each entry becomes one record. Its `type` picks the kind, and `SURVEY` needed a new kind, `survey`."

If they ask "how do you add Zendesk": "Five steps: an enum value, a metadata model, a connector file, a
registry entry and fixtures; the contract test fails until all five exist, and the pipeline, worker and API do
not change. The custom connector was added exactly this way." (The full recipe: ADR-003 "How to add a new
source".)

Then the table **`feedback_records`** [adapters/sqlalchemy/feedback_store.py]: common columns (`kind:
review|conversation|post|survey`, `text, title, author, language, rating, source_created_at,
source_updated_at, deleted_at, connector_version`) plus `metadata` JSON validated per source. Say: "One row is
one Feedback Record. Unique on (source, external id). The upsert only applies a version that is not older,
which is the version guard. Deletes are tombstones and stay set. Replaying the raw table rebuilds this table."

## 4. Reads and tenancy (1 minute)

Draw `GET /v1/records?source_id&kind&since` [api/records.py] and `GET /v1/sources` [api/sources.py]. Draw a
key icon. Say: "Every tenant route carries an API key. Three routes do not: `/health`, the webhook, and
`POST /admin/tenants`, which takes a bootstrap token instead. We store only the key's hash. Every read is
filtered by that tenant; a foreign id is a 404, not a 403, so we do not leak existence. A source is one
configured instance, so two Playstore apps are two rows with their own secrets and cursors."

## 5. Operations (1 minute)

Draw `GET /health`, `GET /admin/raw-events?status=dead`, `POST /admin/raw-events/{id}/replay` and
`POST /admin/raw-events/replay` [api/health.py, api/admin.py]. Say: "Health tells me three things. Are the
worker and scheduler threads alive. How many pull sources failed their last scheduled sync: a count in the
body, no ids. And how deep the queue is. Health answers 503 when either thread is dead, or the worker has made
no progress for about 10 seconds, or storage is down, because it reads the queue counts. A failing source only shows in the count and does not
change the status code, because restarting us would not fix someone else's API. Dead
events are listed per tenant, newest first. I replay one by id, or many at once with the bulk replay, by
status and optionally by source. Every worker and pipeline line about an event carries the raw event id, so
one id takes me from ingress to record. Pull log lines carry the source id instead, and startup lines show a dash."

## 6. The three guarantees (close, 1 minute)

Write them in a corner and point at the boxes:

1. **Durable before ack.** The insert commits before the 202. DB down means 503 and the sender retries.
   Accepted does not mean processed: Enterpret's public webhook docs say the same about their 200.
2. **Idempotent by key.** (source, external id) on records; (source, external event id) on raw events.
3. **Replayable.** The parsed JSON payload is saved before we answer (not the raw bytes, so the signature
   cannot be re-checked from storage; a pulled Discourse post also carries the topic title we add); a
   connector fix plus replay rebuilds records.

## What to draw when they push on something

| They ask | Draw | Say |
|---|---|---|
| Two workers | Second worker box, same claim arrow | "Same single UPDATE. On Postgres I add SKIP LOCKED to that one query." |
| 10k burst | Thick arrow into the table | "Inserts are cheap, the 202 stays fast, the backlog drains at the worker's pace. SQLite is one writer. Past that I move to Postgres (extensions recipe 2)." |
| Edits out of order | Two arrows into one record, timestamps | "COALESCE(updated, created) must not be older. Equal is accepted, so replay works. That is the COALESCE rule, applied in Python today inside BEGIN IMMEDIATE; the SQL ON CONFLICT … WHERE form is the Postgres upgrade (extensions recipe 2). Their engineering blog describes the same idea: version-based rejection of stale updates." |
| Source deletes | Tombstone column | "Only Discourse push payloads carry a delete today and it becomes a tombstone; Twitter and Intercom deletes go dead on purpose; pull-side Discourse deletes are invisible (README § not built)." |
| Transformer bug last week | Arrow from raw_events back into the pipeline | "Fix the connector, bump its version, replay. No re-fetch, nothing lost." |
| Noisy tenant | Two tenants' arrows into one queue | "Today one queue, so one tenant's burst delays the others. That is a noisy neighbour. Their engineering blog says they partition events by tenant for this reason. My next step is the same idea: claim round-robin by tenant, then a partition per tenant or tier." |
| Kafka | Box behind the queue port | "Swap the adapter, and change the retry model. Kafka: consumer offsets instead of leases, and retry topics because there is no per-message delay. SQS would use a visibility timeout." |
| Where it fits in Enterpret | Arrow out of feedback_records to a box "Understand" | "We are Unify. Records go downstream to the taxonomy and Wisdom. Their blog names ClickHouse as the analytics tier; that would be a projection fed from these records. PII redaction before storage is on their public pages; we did not build it." |
| Did you write this | Nothing | "I designed it and reviewed every file; AI agents wrote and audited the code. Every big decision was argued by five independent advisor agents and is written up in docs/decisions." |

## Ports and adapters, if they ask about the layering

Draw a dashed vertical line. Left: services (ingestion, pipeline, worker, pull, scheduler). Right: adapters
(SQLAlchemy stores and queue, httpx client, system clock) and their in-memory fakes. On the line: ports
[ports/*.py], small Protocols. Say: "Services only import the ports. The same contract test runs against the
SQLite adapter and the in-memory fake, so I know the fake behaves like the real thing. That is why a Postgres
swap stays inside the adapters (extensions recipe 2)."

## Things never to claim

- Never say SKIP LOCKED runs today. It is the Postgres upgrade line.
- Never say Kafka is a one-adapter swap without adding "and a different retry model".
- Never say Playstore pushes webhooks. Real Play reviews are polled; fixtures stand in for that poller.
- Never say language is detected. The field is filled when the source provides it; detection is an
  enrichment stage we did not build.
- Never say the queue is an "outbox". It is an inbox, a durable log.
- Never say "Enterpret does X internally". Say "their public docs describe" or "their engineering blog says".
