# Extensions: how to grow it

Numbered recipes for "how would you add X?". Each one names the files to touch, in order, and the honest catch.
None of these are built, except that recipe 1 has a worked example in the code (the `custom`
connector). Every recipe says what is true in the code today, so you can tell "built" from
"planned" out loud.

Paths are from the repo root. Terms are in [glossary.md](glossary.md). "Why not X" is in
[alternatives.md](alternatives.md); the spoken answers are in [qa_bank.md](qa_bank.md).

| # | Recipe | Size | Touches the core? |
|---|---|---|---|
| 1 | Add a source (Zendesk; worked example: `custom`) | 5 files | No |
| 2 | Postgres swap | 1 setting, 1 dependency, 3 queries, migrations | Adapters only |
| 3 | Kafka or SQS swap | 1 new adapter, a new retry model | Adapter, plus the retry story |
| 4 | Horizontal workers | Deployment, plus one small entry point | No |
| 5 | Per-tenant fairness (noisy neighbour) | 1 query, or 1 check at the door; later, a partition per tenant | Adapter or route |
| 6 | Enrichment (PII redaction first, then language, sentiment) | 1 step in accept; 1 table, 1 worker, 1 column | Ingestion, plus a new stage beside the pipeline |
| 7 | GDPR erasure and raw-event retention | 1 job, 1 endpoint, maybe 1 column | Adapter and admin API |
| 8 | Backfill | 1 endpoint, 1 small service change | Pull service |
| 9 | Shadow-run a new connector version | 1 script | No |
| 10 | Generic JSON-webhook connector | 1 connector file | No |
| 11 | Observability | Counters, 1 endpoint, log fields | Pipeline and API |

---

## 1. Add a source (Zendesk), in 5 steps

The recipe: (1) a `SourceType` value and its `KIND_BY_SOURCE` entry in `domain/enums.py`; (2) a metadata model in the `SourceMetadata` union in `domain/metadata.py`; (3) a connector file with its input model in `connectors/`; (4) its entry in `CONNECTORS` (and `PULLERS` if it pulls) in `connectors/registry.py`; (5) fixtures under `tests/fixtures/<type>/`. The contract test fails until all five exist.

The tests fail until all five steps are done. `tests/unit/connectors/test_registry.py` and
`tests/unit/test_models.py::test_every_source_type_has_a_metadata_model` check that every type has a connector,
a kind, a metadata model and a `malformed` fixture. The contract tests in `tests/unit/connectors/test_contract.py`
then run every fixture. That is the point: you cannot half-add a source.

1. **Name it.** In `feedback_ingest/domain/enums.py` add `ZENDESK = "zendesk"` to `SourceType`. In the
   same file add it to `KIND_BY_SOURCE`, reusing a kind (a ticket is a `conversation`).
   Now `tests/unit/connectors/test_registry.py` fails, because the registry has no connector for the new type.
2. **Metadata model.** In `feedback_ingest/domain/metadata.py` add `ZendeskMetadata` with
   `source_type: Literal[SourceType.ZENDESK] = SourceType.ZENDESK` and only the fields that are not already
   record columns (for example `priority`, `tags`). Give every optional field a default. Add it to the
   `SourceMetadata` union. `tests/unit/test_models.py` checks every type has one.
3. **Connector file.** Write `feedback_ingest/connectors/zendesk.py`, copying the shape of `playstore.py`:
   - a Pydantic input model (`ZendeskTicketIn`) shaped like the real payload;
   - `source_type`, `version = 1`, `required_config = ()`;
   - `external_event_id(payload)`: `f"{ticket id}:{updated_at}"`, falling back to `payload_hash` on a
     `ValidationError`, so it never raises;
   - `transform(source, payload)`: validate first, return a list (empty for non-feedback events), each record
     built with `new_record(source, self, external_id, ...)` from `connectors/base.py`;
   - `verify_signature`: Zendesk signs a timestamp header plus the body with HMAC-SHA256, base64, in
     `X-Zendesk-Webhook-Signature`, so override the default here.
   - Add `pull` and `pull_config` only if Zendesk will be polled.
4. **Register it.** In `feedback_ingest/connectors/registry.py` add `ZendeskConnector()` to the tuple that
   builds `CONNECTORS` (and to `PULLERS` if it pulls). mypy checks it against the Protocol on that line.
5. **Fixtures and one golden test.** Add `tests/fixtures/zendesk/ticket.json`, `ticket_edited.json` (same id,
   later `updated_at`) and `malformed.json`, all synthetic. The contract test needs the edited pair to prove
   an edit is a new event and the newer text wins, and needs `malformed` to prove it goes dead. Add
   `tests/unit/connectors/test_zendesk.py` for Zendesk's odd cases.

Catch to say out loud: `test_verify_signature_accepts_signed_body_and_rejects_tampered` in
`tests/unit/connectors/test_contract.py` signs with the default `X-Signature` header. A connector that overrides
the signature needs that test taught its scheme.

Not touched: routes, services, the worker, the tables. Run `uv run pytest tests/unit/connectors` until green.

### Worked example: the `custom` connector (built)

This is exactly the five-step recipe, done against Enterpret's public webhook shape
(`{"records": [{id, type, createdAt, text, title?, metadata}]}`, see `docs/research/01_product_and_integrations.md`):

1. `SourceType.CUSTOM` in `domain/enums.py`, plus one new kind, `FeedbackKind.SURVEY`. The one twist: a custom
   source carries several kinds, so instead of a `KIND_BY_SOURCE` entry, `domain/enums.py` has
   `KIND_BY_RECORD_TYPE` (`REVIEW`→review, `CONVERSATION`→conversation, `FORUM_CONVERSATION_THREAD`→post,
   `SURVEY`→survey), and the custom connector passes `kind=KIND_BY_RECORD_TYPE[record.type]` to `new_record`.
   That is the only place the rule lives.
2. `CustomMetadata(record_type, score, fields)` in `domain/metadata.py`, in the union; `fields` is flat
   string/number/bool metadata, `score` is lifted out of `metadata["score"]`.
3. `connectors/custom.py`: input models `CustomBatchIn` / `CustomRecordIn` (epoch seconds or milliseconds),
   one record per entry, `external_event_id` = hash of the whole batch (one delivery), default HMAC, no config.
   Any other `type` is a `PermanentError`, so the batch goes dead with "unsupported record type".
4. `CustomConnector()` in the `CONNECTORS` tuple; no puller.
5. `tests/fixtures/custom/` (`batch`, `batch_edited`, `malformed`, `unsupported_type`), golden tests in
   `tests/unit/connectors/test_custom.py`, and `tests/api/test_custom_webhook.py` (one push, three records of three
   kinds, a resend is a duplicate). Demo step 6 pushes the batch.

Their semantics already matched ours: a resent delivery is a duplicate (raw-event key), a newer `updatedAt`
wins on upsert, and 202 means accepted, not processed. Not copied: their nested typed metadata arrays (we take
the flat form), the `surveyResponse` / `conversation.msgs` content shapes (we take one `text`), and partial
acceptance of a batch (one bad record dead-letters the batch; marked `ponytail:` in `custom.py`).

---

## 2. Postgres swap

What is true today: `make_engine` only adds the SQLite settings (WAL, `busy_timeout`, foreign keys,
`BEGIN IMMEDIATE`) when the URL is SQLite (`feedback_ingest/adapters/sqlalchemy/db.py`). There is no Postgres
driver in `pyproject.toml`.

1. **Driver and URL.** `uv add "psycopg[binary]"`, then set
   `FI_DATABASE_URL=postgresql+psycopg://user:password@host/dbname` (the `database_url` setting in
   `feedback_ingest/config.py`; the env prefix is `FI_`).
2. **The SKIP LOCKED line.** In `feedback_ingest/adapters/sqlalchemy/raw_event_queue.py`, `claim` builds the
   subquery as `due.limit(limit).scalar_subquery()`. On Postgres it becomes
   `due.limit(limit).with_for_update(skip_locked=True).scalar_subquery()`. Keep the repeated `claimable` check on
   the outer `UPDATE`. "Skip locked" means each worker skips rows another worker is claiming, instead of
   waiting for them. Never say this runs today: SQLAlchemy ignores it on SQLite.
3. **The upsert.** `upsert` in `feedback_ingest/adapters/sqlalchemy/feedback_store.py` reads, then writes. On
   SQLite that is safe because `BEGIN IMMEDIATE` lets only one writer in. On Postgres two first inserts of the
   same item can race, and the loser gets an `IntegrityError`; the pipeline treats it as unexpected and retries,
   so it is safe but noisy. Fix: `INSERT ... ON CONFLICT (source_id, external_id) DO UPDATE ... WHERE` with the
   version guard, keeping the tombstone rules (never clear `deleted_at`; an older delete still sets it). Its
   `ponytail:` comment marks this.
4. **The enqueue.** `enqueue` in the same queue file also reads, then inserts. On Postgres a race would raise
   `IntegrityError`, which is not mapped to 503, so the sender would see a 500 and retry into a clean
   duplicate. Fix: `INSERT ... ON CONFLICT (source_id, external_event_id) DO NOTHING` and check whether a row
   came back.
5. **Migrations.** `create_all` makes missing tables but never changes existing ones, and
   `assert_schema_matches` refuses to start if a column is missing. Add Alembic: a baseline migration generated
   from `Base.metadata` in `feedback_ingest/adapters/sqlalchemy/tables.py`, run on deploy, and drop `create_all`
   from `feedback_ingest/wiring.py`.
6. **Prove it.** Point the `engine` fixture in `tests/conftest.py` at a Postgres URL and run
   `tests/adapters/test_sqlalchemy.py`. The contract cases and `test_concurrent_claims_are_disjoint` are the
   proof. The WAL test is SQLite-only and should be skipped there.

Optional: the `JSON` columns can become `JSONB` for indexing inside `metadata`.

---

## 3. Kafka or SQS swap

The port is `RawEventQueue` in `feedback_ingest/ports/queue.py`. A new adapter would live next to the others,
for example `feedback_ingest/adapters/sqs/queue.py`, and be wired in `feedback_ingest/wiring.py`. Services do not
change. The retry model does, and that is the honest part.

How each port method maps:

| Port method | Our table today | SQS | Kafka |
|---|---|---|---|
| `enqueue` | insert, unique key drops repeats | send; FIFO queues dedupe only within a 5-minute window | produce, keyed by `source_id`; no dedupe |
| `claim` (lease) | `lease_until = now + 30 s` | receive with a visibility timeout (the message hides, then reappears) | poll; the partition is yours until rebalance |
| `mark_processed` | status `processed` | delete the message | commit the offset |
| `mark_failed` (delay) | `next_attempt_at = now + 2^attempts` | change the message's visibility to the delay | no per-message delay: publish to a retry topic, commit |
| `mark_dead` | status `dead` | a dead-letter queue after N receives | publish to a dead topic |
| `replay` | `UPDATE` to pending | move back from the dead-letter queue | republish |
| fence | `attempts` plus `lease_until` must match | the receipt handle is the closest thing; weaker | none; rely on the idempotent upsert |
| `get`, `list_by_status`, `counts` | plain SQL | not available | not available |

What to say:
- The lease maps well to an SQS visibility timeout. Our per-message delay maps to SQS too. Kafka has neither,
  so retries move to retry topics, and one slow message can hold up its partition.
- A broker cannot answer "show me tenant X's dead events" or "give me event 42". So the realistic design keeps
  `raw_events` as the durable log and source of truth, and puts only event ids on the broker. Then replay,
  the admin API and the firefight runbook keep working.
- The queue contract tests in `tests/adapters/contract_queue.py` would not all pass on a broker, because of the
  last row above. That is a sign the port would split into "transport" and "event log".

---

## 4. Horizontal workers

What is true today: the claim is one atomic statement and finishes are fenced, so several workers are already
safe; a test runs four threads on 40 events (`tests/adapters/test_sqlalchemy.py`,
`test_concurrent_claims_are_disjoint`). The limit is SQLite's single writer.

1. Do recipe 2 first. More workers on one SQLite file mostly wait for the write lock.
2. Run the API without the background threads: `FI_WORKER_ENABLED=false FI_SCHEDULER_ENABLED=false`.
3. Run worker processes. The laziest way works today: the same app on another port with the worker on and no
   traffic routed to it. The clean way is a small `feedback_ingest/worker_main.py`. It opens `sql_adapters`
   from `feedback_ingest/wiring.py` (which builds the adapters), builds `PipelineService` and `WorkerService`
   the way the `main.py` lifespan does (that is where the services are built today), calls `worker.start()`,
   and waits for a signal.
4. Turn the scheduler on in exactly one process. N schedulers are safe (repeats are dropped) but call Discourse
   N times per interval.
5. Tune `FI_CLAIM_BATCH` and `FI_LEASE_SECONDS`. The lease must be longer than the slowest transform, or a second
   worker will claim the row while the first is still on it (safe, but wasted work and a `lease lost` warning).
   For long jobs, add a lease heartbeat.
6. Each process has its own `/health`; a supervisor restarts any worker whose health is 503.

---

## 5. Per-tenant fairness

What is true today: `claim` takes the rows due soonest across all tenants
(`feedback_ingest/adapters/sqlalchemy/raw_event_queue.py`). One tenant's burst delays everyone. Per-tenant counts
are already on `GET /admin/queue`.

Two fixes, cheapest first:

1. **Limit at the door.** In `feedback_ingest/api/ingest.py`, before `accept`, check the tenant's pending count
   and answer 429 with `Retry-After` when it is over a limit. The sender retries later. Cheap, but it is one
   extra count query per webhook, and a pull source would need the same check in `feedback_ingest/services/pull.py`.
2. **Fair claim.** Change the `due` subquery so it ranks rows inside each tenant and takes the first few of each:
   `ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY next_attempt_at) <= k`. SQLite has window functions, so
   this works on both databases. Add an index on `(tenant_id, status, next_attempt_at)` in
   `feedback_ingest/adapters/sqlalchemy/tables.py`. Add the same rule to the memory fake in
   `feedback_ingest/adapters/memory/queue.py`, and one contract case: tenant A has 100 due rows, tenant B has 1,
   and `claim(limit=10)` must include B's row.

Bigger step: partition the queue per tenant (or per plan tier), so one tenant's backlog can never sit in
front of another's. Enterpret's engineering blog says they partition events by tenant and object type, and
names noisy neighbours and queue clogging as incidents. We have not built this; it is our named upgrade.
On this design it means a `tenant_id` filter in the claim, one claim loop per partition, and weights per tier.

---

## 6. Enrichment stage (PII redaction, language, sentiment)

What is true today: `language` is filled only when the source sends it. There is no enrichment. We keep PII
out of logs and error text, and nothing more.

**The first stage we did not build: PII redaction before storage.** Enterpret's public pages say they detect
and obfuscate PII (card numbers, SSNs) before ingestion. Here it cannot be a later stage, because `raw_events`
keeps every payload verbatim. It goes in `IngestionService.accept` (`feedback_ingest/services/ingestion.py`):
compute `external_event_id` from the original payload first (so duplicates still match), then replace emails,
phone numbers and card numbers with placeholders like `[EMAIL]`, then enqueue. The HMAC check already ran on
the raw bytes, so it is not affected. The catch to say out loud: once raw is redacted, replay can never get the
original text back. That is the point, and the trade-off.

The later stages (language, sentiment) run after the record exists:

Use the same pattern as `raw_events`: a durable job table, a worker that claims with a lease, and idempotent
writes.

1. **Where results go.** Add new columns, for example `detected_language` and `sentiment`, or a separate
   `record_enrichments` table keyed by record id. Do not write into `language`. Reason: `upsert` in
   `feedback_ingest/adapters/sqlalchemy/feedback_store.py` rewrites every field on each update, so an edit would
   wipe a detected value.
2. **Jobs.** An `enrichment_jobs` table with the same bookkeeping columns as `raw_events` (`status`, `attempts`,
   `next_attempt_at`, `lease_until`, `error`), unique on `(feedback_record_id, enricher_version)`. Copy the claim and
   fence logic from `raw_event_queue.py`; generalise it only when a third queue appears.
3. **Producing jobs.** In `feedback_ingest/services/pipeline.py`, after each upsert that returns `inserted` or
   `updated`, enqueue a job for that record. A re-edit re-enqueues, so the result follows the latest text.
4. **The worker.** An `EnrichmentService` beside `PipelineService`: claim, compute, write, mark done. A model
   timeout is transient (retry); an empty text is "nothing to do" (done).
5. **Versioning.** Stamp `enricher_version`. A better model means a new version and a re-run over records, like
   connector replay.

Why a separate stage and not inline in the pipeline: a slow model would slow ingestion, and a model outage
would turn into ingestion retries.

---

## 7. GDPR erasure, and raw-event retention

What is true today: a tombstone hides a record but keeps its text. Raw payloads are kept forever, and
`GET /admin/raw-events/{id}` returns them to their own tenant.

**Erasure request** ("delete everything about this item or this person"):

1. **Records.** Find them by tenant and `external_id` (or by `author`). Hard-delete the row, or scrub it (empty
   `text`, null `title` and `author`, minimal `metadata`) and set `deleted_at`.
2. **Raw events.** Hard-delete every raw event for that item. Catch: `raw_events` has no `external_id` column.
   Most event ids start with the item id (`"<id>:<time>"`), so `external_event_id LIKE '<id>:%'` finds most of
   them, but payloads keyed by a hash need a search inside the JSON. The clean fix is a nullable `external_id`
   column on `raw_events`, filled at ingress by the connector.
3. **Stop it coming back.** A later webhook or poll would re-create the item. Keep an erasure list of
   `(source_id, external_id)` and have the pipeline drop matching events.
4. **Expose it.** One admin endpoint per tenant, for example `POST /admin/erasures`, in `feedback_ingest/api/admin.py`.
5. **Elsewhere.** Logs carry ids, not text (`feedback_ingest/services/pipeline.py`), so they mostly need nothing;
   backups and any analytics copy do.

**Retention:** a scheduled job that deletes `processed` raw events older than N days:
`DELETE FROM raw_events WHERE status = 'processed' AND received_at < :cutoff`. Keep `dead` and `failed` rows until
someone resolves them. The trade-off to say: after N days you can no longer replay those events. On Postgres,
partition `raw_events` by month and drop old partitions instead.

---

## 8. Backfill

What is true today:
- Push: the client re-sends its history. Repeats are dropped and edits update. Nothing to build.
- Pull: `POST /v1/sources/{id}/sync` takes no date range (`feedback_ingest/api/sync.py`). `start_after` is used only
  while the cursor is empty, and `PATCH /v1/sources/{id}` changes `enabled` and `config` (for example
  `window_days`), never the cursor. So today you move `sources.cursor` back by hand in SQL and sync repeatedly;
  each run reads at most `window_days`, and at most 10 search pages (about 500 posts per day is the limit of
  Discourse search). Moving the cursor back is safe.

The real feature:

1. `POST /v1/sources/{id}/backfill` with `from` and `to`, in `feedback_ingest/api/sync.py`.
2. Run the puller on a copy of the source, `source.model_copy(update={"cursor": from})`, until the window passes
   `to`.
3. Do not save that cursor. `PullService.sync` in `feedback_ingest/services/pull.py` always calls `_advance`, which
   writes the live cursor. Add a flag to skip it, or keep a separate backfill cursor.
4. Run it as a background job, not inline: the sync endpoint's own `ponytail:` comment says so.
5. The rest is free: payloads go through the same `accept`, and the unique keys absorb the overlap with live
   data.

---

## 9. Shadow-run a new connector version and diff

Because raw payloads are kept, "try v2 before switching" is a script, not a feature.

1. Write `scripts/shadow_diff.py`. It opens the database with `make_engine`, reads `processed` raw events for one
   source type, and loads each event's source.
2. Run the new transform, `ZendeskConnectorV2().transform(source, payload)`, on each payload. It writes nothing.
3. Each v2 record is built by `new_record(source, self, external_id, ...)`, so its `id` is the same id the stored
   record has. Load the stored one with `FeedbackStore.get(record.id, source.tenant_id)` and compare field by
   field, ignoring `ingested_at` and `connector_version`.
4. Print counts: same, changed (by field name), new, missing, and v2 errors. Print field names, not customer text.
5. When the diff is what you expect: bump `version`, deploy, replay the events. Replay in any order is safe: an
   older event is `skipped_older`, and the newest one is rewritten because equal versions are accepted.

---

## 10. A generic JSON-webhook connector

For simple flat sources where field mapping really is the whole job. (A sender that can adopt a fixed shape
already has one: the built `custom` connector, recipe 1's worked example. This recipe is for senders that
cannot change their payload.) ADR-003 rejected config-driven mapping as
the core design, because identity, edits, threads and paging are the hard parts. This is one more connector
behind the same Protocol, not a new core.

1. Add `SourceType.GENERIC` and map it to one kind in `KIND_BY_SOURCE` (`post` is the safe choice).
2. `GenericMetadata` in `feedback_ingest/domain/metadata.py` with an `extra: dict[str, str]` for chosen fields.
3. `feedback_ingest/connectors/generic_json.py`:
   - `required_config = ("id_path", "text_path", "created_at_path")`, plus optional `updated_at_path`,
     `author_path`, `title_path`;
   - a tiny dotted-path reader (`"ticket.requester.name"`, numbers for list indexes); no JSONPath library;
   - `transform` reads paths from `source.config`, validates the result through `FeedbackRecord` as usual, and
     raises `PermanentError` when a required path is missing.
4. Catch: `external_event_id(payload)` gets no `source`, so it cannot read the configured paths. It falls back to
   `payload_hash`. That still works: an identical resend is a duplicate, and an edit changes the hash, so it is
   a new event.
5. Signature: the default `X-Signature` HMAC. `check_source` already enforces `required_config` at creation.

---

## 11. Observability (metrics, tracing by raw_event_id)

What is true today:
- Every log line has `raw_event_id`, `tenant_id`, `source_id` and `attempts`, defaulting to `-`
  (`feedback_ingest/main.py`). Every worker and pipeline line carries `raw_event_id`, and the `accepted` line
  carries it too, with the stored row's id even on a duplicate. One grep traces an event:
  `grep "raw_event_id=<id>" server.log`.
- The one hole: pull lines carry `tenant_id` and `source_id` but no `raw_event_id`. Startup lines show `-`.
- `/health` has worker and scheduler liveness, `failing_sources` (a count of pull sources whose last scheduled
  sync failed, no ids) and queue counts. In-process counters (`processed_total`, `dead_total`, uptime) are not
  built.

Recipe:

1. **Counters.** In `feedback_ingest/services/pipeline.py`, count each final status by `source_type` in `_mark_outcome`.
   Start as plain integers behind a lock on `/health`; move to a Prometheus client with a `/metrics` route once
   something scrapes it.
2. **Queue age.** Add `oldest_pending_at` to the queue port and both adapters (`MIN(received_at)` for pending).
   Queue age is a better alarm than queue length.
3. **Per-source pull health.** Store the last successful sync time on the source and expose it. Alert when it
   is older than a few intervals.
4. **Alerts that would have caught the firefight:** dead count per source jumps; oldest pending older than five
   minutes; no new records for a source in N hours; `/health` 503.
5. **Tracing.** A span per webhook with `raw_event_id` as an attribute. The worker runs later, in another thread,
   so to join the two traces store a `traceparent` column on `raw_events` at ingress and start the worker span
   from it. Until then, `raw_event_id` is the join key.
