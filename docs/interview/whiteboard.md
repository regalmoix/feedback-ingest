# Whiteboard script (10 minutes)

Draw in this order. Each step is one box or arrow and one sentence. Module names in brackets are the real
files, so if someone opens the repo the drawing matches.

## 0. The one sentence (say it before drawing anything)

"We save the raw payload to disk before we say yes. Everything after that is a retry or a replay."

## 1. Two doors in, one pipe (2 minutes)

Draw a box on the left: **Source** (Intercom, Playstore, Twitter, Discourse). Two arrows out of it.

- Arrow 1, **push**: `POST /v1/sources/{id}/events` [api/ingest.py]. Say: "The webhook does three checks and one
  write. Whose tenant (API key), which source (id must belong to that tenant), is the signature right (HMAC
  over the raw bytes with that source's secret). Then one insert, then 202. 202 means saved, not processed."
- Arrow 2, **pull**: `POST /v1/sources/{id}/sync` or the scheduler tick [api/sync.py, services/scheduler.py,
  services/pull.py]. Say: "Polling is just another producer. The connector returns pages; every payload goes
  through the same accept call a webhook uses."

Both arrows land on one box: **`IngestionService.accept`** [services/ingestion.py]. Under it draw the table:
**`raw_events`** with columns `status, attempts, next_attempt_at, lease_until, external_event_id`
[adapters/sqlalchemy/raw_event_queue.py]. Say: "This table is both the audit log and the work queue. Unique on
(source, external event id), so a repeated webhook is stored once."

If asked "why not a real queue": "A table I can query, replay by id and filter per tenant. It is one process
and zero infrastructure for a demo. The adapter boundary is where Kafka or SQS would go, and I would be honest
that a broker changes the retry model, not just the adapter."

## 2. The engine (2 minutes)

Draw a box to the right of the table: **Worker thread** [services/worker.py]. Arrow from the table labelled
"claim with lease". Say: "One SQL statement: update rows that are pending-and-due or whose lease expired, set
processing and a lease, return them. Atomic, so two workers never take the same row. A crashed worker's rows
come back when the lease expires."

Below the worker: **`PipelineService.process`** [services/pipeline.py]. Three outcomes, draw three arrows back
to the table:
- processed
- failed, with `next_attempt_at = now + 2^attempts` (capped), retried later
- dead after max attempts, or immediately for a bad payload (validation error)

Say: "Bad payloads die on the first try, they are never retried. Flaky things back off. Marks are fenced on
the lease, so a stale worker cannot overwrite a newer claim."

## 3. The translation (2 minutes)

Between the pipeline and the records table draw: **`CONNECTORS[source.type]`** [connectors/registry.py] with
four small boxes: discourse, playstore, twitter, intercom [connectors/*.py]. Say: "A connector validates the
payload with a Pydantic input model, then maps it to our record. Nothing else in the system knows which
sources exist. Adding Zendesk is one file, one metadata model, one registry entry, one fixture; the contract
test fails until all four exist."

Then the table **`feedback_records`** [adapters/sqlalchemy/feedback_store.py]: common columns (`kind:
review|conversation|post`, `text, title, author, language, rating, source_created_at, source_updated_at,
deleted_at, connector_version`) plus `metadata` JSON validated per source. Say: "Unique on (source, external
id). The upsert only applies a version that is not older. Deletes are tombstones and always win. Replaying
the raw table rebuilds this table."

## 4. Reads and tenancy (1 minute)

Draw `GET /v1/records?source_id&kind&since` [api/records.py] and `GET /v1/sources` [api/sources.py]. Draw a
key icon. Say: "Every request carries an API key. We store only its hash. Every read is filtered by that
tenant; a foreign id is a 404, not a 403, so we do not leak existence. A source is one configured instance,
so two Playstore apps are two rows with their own secrets and cursors."

## 5. Operations (1 minute)

Draw `GET /health` and `GET /admin/raw-events?status=dead` and `POST /admin/raw-events/{id}/replay`
[api/health.py, api/admin.py]. Say: "Health tells me the worker and scheduler are alive and how deep the queue
is. Dead events are listed per tenant, newest first, and replayed with one call. Every log line carries the
raw event id, so one id takes me from ingress to record."

## 6. The three guarantees (close, 1 minute)

Write them in a corner and point at the boxes:

1. **Durable before ack.** The insert commits before the 202. DB down means 503 and the sender retries.
2. **Idempotent by key.** (source, external id) on records; (source, external event id) on raw events.
3. **Replayable.** Raw payloads are kept verbatim; a connector fix plus replay rebuilds records.

## What to draw when they push on something

| They ask | Draw | Say |
|---|---|---|
| Two workers | Second worker box, same claim arrow | "Same single UPDATE. On Postgres I add SKIP LOCKED to that one query." |
| 10k burst | Thick arrow into the table | "Inserts are cheap, the 202 stays fast, the backlog drains at the worker's pace. SQLite is one writer; past that, DATABASE_URL points at Postgres." |
| Edits out of order | Two arrows into one record, timestamps | "COALESCE(updated, created) must not be older. Equal is accepted, so replay works." |
| Source deletes | Tombstone column | "deleted_at set, hidden by default, never undone by a later edit." |
| Transformer bug last week | Arrow from raw_events back into the pipeline | "Fix the connector, bump its version, replay the window. No re-fetch, nothing lost." |
| Noisy tenant | Two tenants' arrows into one queue | "Today one queue. Next: claim round-robin by tenant, or a queue per tier." |
| Kafka | Box behind the queue port | "Swap the adapter, and change the retry model: visibility timeout instead of leases, no per-message delay." |
| Did you write this | Nothing | "I designed it and reviewed every file; AI agents wrote and audited the code. Every decision went through a five-advisor council and is in docs/decisions." |

## Ports and adapters, if they ask about the layering

Draw a dashed vertical line. Left: services (ingestion, pipeline, worker, pull, scheduler). Right: adapters
(SQLAlchemy stores and queue, httpx client, system clock) and their in-memory fakes. On the line: ports
[ports/*.py], small Protocols. Say: "Services only import the ports. The same contract test runs against the
SQLite adapter and the in-memory fake, so I know the fake behaves like the real thing. That is how a Postgres
or broker swap stays a one-file change."

## Things never to claim

- Never say SKIP LOCKED runs today. It is the Postgres upgrade line.
- Never say Kafka is a one-adapter swap without adding "and a different retry model".
- Never say Playstore pushes webhooks. Real Play reviews are polled; fixtures stand in for that poller.
- Never say language is detected. The field is filled when the source provides it; detection is an
  enrichment stage we did not build.
- Never say the queue is an "outbox". It is an inbox, a durable log.
