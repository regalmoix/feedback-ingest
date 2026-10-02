# Q&A bank

About 40 questions an interviewer is likely to ask, grouped by topic. Each one has:

- **Say:** two sentences you can say out loud.
- **Go deeper:** what to add if they push.
- **Point at:** where it lives in the repo.

Paths are from the repo root. Words like lease, fence, tombstone, cursor and dead letter are defined in
[glossary.md](glossary.md). Rejected options and "when would you switch" are in
[alternatives.md](alternatives.md). Outage symptoms are in [failure_scenarios.md](failure_scenarios.md), and
live-incident steps in [firefight_runbook.md](firefight_runbook.md). This file does not repeat those tables; it
gives you the spoken answer and sends you there for the detail.

Three sentences answer half of these questions. Learn them first:

1. "We save the raw payload to disk before we say yes. Everything after that is a retry or a replay."
2. "Every record is keyed on source plus the source's own id, so doing something twice gives one row."
3. "Bad payloads go to a dead list on the first try; flaky failures back off and retry."

---

## 1. Design choices

### Q1. Why SQLite?

**Say:** It needs zero infrastructure, so the demo is one process and one file, and the grading is on code and
extensibility, not on running a database. The connection string is a setting, so moving to Postgres is a URL
change plus a few named queries, not a rewrite.

**Go deeper:** SQLite allows one writer at a time. We make that safe with three settings on every connection:
WAL (readers keep reading while one writer writes), `busy_timeout=5000` (a writer waits up to 5 seconds instead
of failing), and `foreign_keys=ON` (so the database refuses a record whose tenant differs from its source's
tenant). The ceiling is write throughput. Past that, we point `FI_DATABASE_URL` at Postgres. The exact changes
are recipe 2 in [extensions.md](extensions.md).

**Point at:** `feedback_ingest/adapters/sqlalchemy/db.py` (`make_engine`), `feedback_ingest/config.py`
(`database_url`), `docs/decisions/ADR-001-storage-and-queue.md`.

### Q2. Why is a database table your queue?

**Say:** The `raw_events` table is both the audit log and the work queue, so every payload is on disk before we
reply, and I can query it, count it per tenant, and replay any row by id. A broker gives none of that for free,
and it is a second system to run.

**Go deeper:** A worker takes work with one SQL statement that sets `status='processing'` and a lease time and
returns the rows. Retries are just a `next_attempt_at` column. Dead letters are just `status='dead'`. Replay is
an `UPDATE` back to pending. Push and pull both write here, so there is one pipeline. Call it an inbox or a
durable log, never an outbox: an outbox holds messages we will send out.

**Point at:** `feedback_ingest/adapters/sqlalchemy/raw_event_queue.py`, `feedback_ingest/adapters/sqlalchemy/tables.py`
(`RawEventRow`), `feedback_ingest/ports/queue.py`.

### Q3. Why not Kafka?

**Say:** Kafka gives huge throughput and ordering per partition, but it has no per-message delayed retry, no
lookup by id, and no "show me the dead events for tenant X". For this volume it is heavy infrastructure that
would change our retry model, not just our adapter.

**Go deeper:** The queue port means the services would not change. But be honest: with Kafka, our
`next_attempt_at` backoff becomes retry topics, and our lease becomes consumer offsets. A stuck message blocks
its partition unless you move it aside. Most real designs keep a table like `raw_events` as the source of truth
and put only event ids on the broker. Never say "it is one adapter and nothing else changes". The full mapping
is recipe 3 in [extensions.md](extensions.md).

**Point at:** `feedback_ingest/ports/queue.py`, ADR-001 "Rejected alternatives".

### Q4. Why put every external thing behind a Protocol port?

**Say:** A port is a small interface the services call, and each one has a real adapter and an in-memory fake.
The same contract tests run against both, so I know the fake behaves like SQLite, and a database or queue swap
stays inside one adapter file.

**Go deeper:** The ports are tenant, source and feedback stores, the raw event queue, an HTTP client and a
clock. Services import only ports, never SQLAlchemy or httpx. The rule from the council was: a port no test
uses through its fake is a port we cannot defend. The clock port exists so lease and backoff tests do not
really sleep; say exactly that. The connector Protocol is the one that matters for extensibility.

**Point at:** `feedback_ingest/ports/`, `feedback_ingest/adapters/memory/`, `tests/adapters/test_memory.py` and
`tests/adapters/test_sqlalchemy.py` (both run the same `*_CASES` lists).

### Q5. Why one record table plus a JSON metadata column?

**Say:** Every source shares the fields people query, like tenant, kind, text, rating, language and dates, so
those are typed columns in one `feedback_records` table. The few source-only fields go in a `metadata` JSON
column that is checked by a Pydantic model per source.

**Go deeper:** A table per source would make every cross-source query a `UNION` and every new source a
migration. Key-value rows (EAV) lose types. The metadata is a "discriminated union": a `source_type` field says
which model it is, and the record refuses metadata whose `source_type` disagrees with its own. A new source
needs a new metadata model, not a new table.

**Point at:** `feedback_ingest/domain/models.py` (`FeedbackRecord`), `feedback_ingest/domain/metadata.py`
(`SourceMetadata`), ADR-002.

### Q6. Why no hash dedupe key?

**Say:** `UNIQUE(source_id, external_id)` already means "this item from this source, once". A sha256 of the same
fields gives the same guarantee and only adds something nobody can read.

**Go deeper:** The tenant comes through the source: one source row belongs to one tenant, so the same id in two
tenants or two apps sits under two different `source_id`s. A content hash would be worse: an edit changes the
hash, so an edited review would become a second record. We do use one hash, on purpose: a raw delivery that
has no usable id gets `payload_hash` as its `external_event_id`, so an identical resend is still caught.

**Point at:** `feedback_ingest/adapters/sqlalchemy/tables.py` (both `UniqueConstraint`s),
`feedback_ingest/utils/hashing.py`, ADR-002 "Uniqueness rule".

### Q7. Why does the webhook return 202 and not 200?

**Say:** 202 means "saved, not finished yet", which is exactly true: the row is committed, and the worker turns
it into a record later. If we cannot save it we return 503, so the sender retries and nothing we accepted is
lost.

**Go deeper:** A duplicate delivery also gets 202, with `"duplicate": true` and `raw_event_id: null`, so the
sender stops retrying. Everything that fails at the door is never stored: a bad API key or bad signature is
401, a foreign source is 404, a disabled source is 409, a body that is not a JSON object is 400. Processing
inside the request would make the sender wait on our transform and lose the event if we crash.

**Point at:** `feedback_ingest/api/ingest.py`, `feedback_ingest/services/ingestion.py` (`AcceptResult`),
`feedback_ingest/api/errors.py` (the 503 mapping).

### Q8. Why threads and not asyncio?

**Say:** The database layer is sync SQLAlchemy on SQLite, and mixing sync and async sessions is where the hours
go. FastAPI runs our sync endpoints in its threadpool, and the worker and scheduler are two plain background
threads.

**Go deeper:** The one async endpoint is the webhook, because it reads the raw body for the signature; it then
hands the insert to the threadpool so the event loop never waits on the database (a test checks this).
`aiosqlite` would still run SQLite on a thread underneath. Our transforms are light, so the GIL is not the
limit. If transforms got heavy, the answer is a separate worker process, not asyncio.

**Point at:** `feedback_ingest/api/ingest.py` (`run_in_threadpool`), `feedback_ingest/services/worker.py`,
`feedback_ingest/services/scheduler.py`, `tests/api/test_push_api.py` (`test_accept_runs_off_the_event_loop`).

### Q9. Why `BEGIN IMMEDIATE`?

**Say:** In SQLite a normal transaction starts as a reader and only asks for the write lock at its first write.
If another writer got there first, the upgrade fails at once with "database is locked", so we take the write
lock up front and let `busy_timeout` make us wait our turn.

**Go deeper:** It also makes our "read, then write" steps atomic: the enqueue duplicate check and the record
upsert both read a row and then write, and no other writer can slip in between. Read-only sessions use a plain
`BEGIN`, so reads never wait on a writer; a test holds the write lock in one connection and checks that reads
still return in under a second. On Postgres this listener does not apply, which is why the upsert and enqueue
need their own upgrade there.

**Point at:** `feedback_ingest/adapters/sqlalchemy/db.py` (`_on_begin`),
`tests/adapters/test_sqlalchemy.py` (`test_reads_do_not_wait_for_the_write_lock`).

### Q10. Why at-least-once plus idempotent, instead of exactly-once?

**Say:** Exactly-once delivery across a network does not really exist; senders retry and workers crash. So we
accept that work can run twice and make running twice give the same result, through two unique keys.

**Go deeper:** `raw_events` is unique on `(source_id, external_event_id)`, so a repeated delivery is stored once.
`feedback_records` is unique on `(source_id, external_id)`, so a second run of the same event updates the same
row. The record id itself is deterministic (a `uuid5` of source and external id), so even the id does not
change. "Effectively once" is the honest name for this.

**Point at:** `feedback_ingest/connectors/base.py` (`record_id`), `feedback_ingest/adapters/sqlalchemy/raw_event_queue.py`
(`enqueue`), `feedback_ingest/adapters/sqlalchemy/feedback_store.py` (`upsert`).

---

## 2. Failure modes

Detailed symptoms for each are in [failure_scenarios.md](failure_scenarios.md). Note: the code is newer than a
few rows there. Today a disabled source refuses pushes (409), a dead scheduler does turn `/health` to 503, the
dead list is newest first, and a payload that crashes the process is dead after `max_attempts` claims. The
answers below match the code.

### Q11. What if the database is down?

**Say:** We cannot save the payload, so the webhook answers 503 and the sender retries; we never say yes to
something that is not on disk. The worker keeps retrying its claim once a second, and `/health` goes red.

**Go deeper:** SQLAlchemy `OperationalError`, `InterfaceError` and `TimeoutError` all map to 503 with
`{"detail": "storage unavailable"}` and an ERROR log line. The worker loop catches the error, logs `worker
iteration failed`, sleeps and tries again; after about 10 seconds without a completed pass, health reports
`degraded`. A pull tick that hits the outage fails for that source and tries again next tick; the cursor only
moves after rows are saved, so nothing is skipped.

**Point at:** `feedback_ingest/api/errors.py`, `feedback_ingest/services/worker.py` (`healthy`, `_loop`),
`tests/api/test_push_api.py` (`test_storage_down_is_503_never_202_and_logged`).

### Q12. What if the worker dies in the middle of an event?

**Say:** The row stays `processing` with a lease end time 30 seconds out. When the lease runs out, the next claim
picks it up again, and the upsert makes the second run the same as the first.

**Go deeper:** Each claim adds one to `attempts`. If the event itself is what crashes the process, it would
crash again on every claim; so the pipeline checks first, and once `attempts` passes `max_attempts` (5) it marks
the event dead without running the transform. A slow worker that comes back after its lease ran out is
stopped by the fence: its finish call only applies if the row still has the same `attempts` and
`lease_until`, so it logs `lease lost` and changes nothing.

**Point at:** `feedback_ingest/adapters/sqlalchemy/raw_event_queue.py` (`claim`, `_finish`),
`feedback_ingest/services/pipeline.py` (the `attempts > max_attempts` check),
`tests/unit/services/test_pipeline_failures.py` (`test_event_past_the_attempt_cap_is_dead_without_transforming`).

### Q13. What if the same webhook arrives twice?

**Say:** The second copy has the same `external_event_id`, so the insert is skipped and we still answer 202 with
`duplicate: true`. If two copies ever did get through, the record upsert would still leave one row.

**Go deeper:** The event id is the item id plus its last-changed time, like `reviewId:lastModified`, or a hash
of the payload when it has no usable id. Including the time matters: a real edit has a new time, so it is a new
event and is not dropped. Demo step 3 shows this live.

**Point at:** `feedback_ingest/services/ingestion.py`, `feedback_ingest/connectors/playstore.py`
(`external_event_id`), `tests/e2e/test_push_to_query.py`.

### Q14. What if an older edit arrives after a newer one?

**Say:** The upsert compares "when did this version last change" on both sides, and an older version loses. So a
late, stale copy is stored in `raw_events` and marked processed, but it does not overwrite the record.

**Go deeper:** "Last changed" is `source_updated_at`, or `source_created_at` when a source sends no update
time. Equal or newer wins, so a re-run of the same version, like a replay, still writes. The store returns
`skipped_older` for the loser. A delete is the exception: it always applies, even if it is older. A contract
test feeds every connector's edit fixtures in both orders and checks the newer text wins.

**Point at:** `feedback_ingest/adapters/sqlalchemy/feedback_store.py` (`upsert`), `feedback_ingest/domain/models.py`
(`version_at`), `tests/unit/connectors/test_contract.py` (`test_an_edit_is_a_new_raw_event_and_the_newer_text_wins`).

### Q15. What about a poison payload?

**Say:** A payload that fails its Pydantic input model, or raises `TransformError`, goes to `dead` on the first
attempt with a short reason. It is never retried and never thrown away, so after a fix we replay it.

**Go deeper:** The error is written as `field: message` pairs without the input values, capped at 500
characters, so customer text does not reach logs or the `error` column. The raw row is still stored, because
`external_event_id` never raises: it falls back to a payload hash. Demo step 6 replays a bad payload and shows
it go dead again, which proves replay really re-runs it.

**Point at:** `feedback_ingest/services/pipeline.py` (`_describe`), `tests/unit/services/test_pipeline.py`
(`test_malformed_payload_is_dead_on_the_first_attempt_without_customer_text`).

### Q16. What happens with a burst of 10,000 events?

**Say:** The webhook does one small insert per event, so 202s stay fast, and the worker drains the backlog ten at
a time without sleeping while there is work. Nothing is lost; other tenants are only slower.

**Go deeper:** SQLite has one writer, so inserts queue behind each other for up to 5 seconds (`busy_timeout`);
past that a sender gets 503 and retries. The claim uses an index on `(status, next_attempt_at)`. There is no
per-tenant limit today, so one tenant's burst delays everyone; admit that and point at the per-tenant counts on
`/admin/queue`. The next steps are a per-tenant rate limit at the door and fair claiming (recipe 5 in
[extensions.md](extensions.md)).

**Point at:** `feedback_ingest/services/worker.py`, `feedback_ingest/config.py` (`claim_batch=10`),
`feedback_ingest/adapters/sqlalchemy/tables.py` (`ix_raw_events_status_next_attempt_at`).

### Q17. What if two workers run at once?

**Say:** It is safe: the claim is one `UPDATE ... RETURNING` statement that repeats the "is this row claimable"
check, so only one worker can flip a row to `processing`. A test runs four threads, each with its own engine,
on 40 events, and every event is claimed exactly once.

**Go deeper:** This happens by accident with `uvicorn --workers N`, which starts N copies of the in-process
worker. The fence stops a late finish from overwriting a newer one. N copies also start N schedulers, which
fetch the same pages; that wastes calls but the unique key drops the repeats. On Postgres, this one query adds
`FOR UPDATE SKIP LOCKED`. Never say that runs today.

**Point at:** `feedback_ingest/adapters/sqlalchemy/raw_event_queue.py` (`claim` and its `ponytail:` note),
`tests/adapters/test_sqlalchemy.py` (`test_concurrent_claims_are_disjoint`).

### Q18. What if Discourse rate-limits us while we pull?

**Say:** The HTTP adapter turns a 429 into a `TransientError`, the pull stops, and the pages already fetched stay
saved. The cursor does not move, so the next tick starts from the same bookmark and the repeats are dropped.

**Go deeper:** 408, 429, 5xx, network errors and the 10-second timeout are all transient; other 4xx are
permanent. The sync result shows `"error": "TransientError: 429 from ..."`. The Discourse cursor only moves on
the final page of a run, because search results are not guaranteed oldest first. Gaps to admit: we do not read
`Retry-After`, and the scheduler does not back off per source; it just tries again every 300 seconds.

**Point at:** `feedback_ingest/adapters/http/httpx_client.py`, `feedback_ingest/services/pull.py` (`sync`),
`feedback_ingest/connectors/discourse_pull.py`, `tests/unit/services/test_pull_failures.py`.

### Q19. The pull cursor is stuck. Why?

**Say:** Four causes: a repeated error like a 429, a window too busy to reach its last page within 20 pages, a
bad cursor or config, or the scheduler is not running or the source is disabled. A manual sync shows which one,
because its result carries the error.

**Go deeper:** A window that needs more than 20 search pages raises after page 20 with the cursor unchanged, so
the result shows `pages: 20` and `"error": "TransformError (see logs)"`; the fix is a smaller `window_days`. An
unparseable cursor is also a `TransformError`. A dead scheduler shows `scheduler_alive: false` and health 503.
Moving the cursor back by hand is always safe because repeats are dropped; moving it forward skips posts. The
step-by-step is Runbook 2 in [firefight_runbook.md](firefight_runbook.md).

**Point at:** `feedback_ingest/connectors/discourse_pull.py` (`_MAX_PAGES`), `feedback_ingest/api/sync.py`,
`feedback_ingest/api/health.py`.

---

## 3. Scale

### Q20. How do you scale the workers horizontally?

**Say:** The claim is already safe for many workers, and the fence and idempotent upsert make overlap harmless.
The real limit is SQLite's single writer, so step one is Postgres, then N worker processes and exactly one
scheduler.

**Go deeper:** Run the API with `FI_WORKER_ENABLED=false`, run worker processes with the worker on, and turn the
scheduler on in only one of them (`FI_SCHEDULER_ENABLED`). Keep `lease_seconds` longer than your slowest
transform, or add a lease heartbeat. Tune `claim_batch`. Recipe 4 in [extensions.md](extensions.md).

**Point at:** `feedback_ingest/services/worker.py` (its `ponytail:` note), `feedback_ingest/config.py`.

### Q21. What exactly changes for Postgres, and where is the SKIP LOCKED line?

**Say:** Set `FI_DATABASE_URL` to a Postgres URL and add a driver; the SQLite pragmas only run for SQLite. Then
the claim subquery gets `.with_for_update(skip_locked=True)`, and the upsert and enqueue move to
`INSERT ... ON CONFLICT`.

**Go deeper:** The claim's `ponytail:` comment marks the spot. `SKIP LOCKED` means "skip rows another
transaction has locked", so workers do not wait on each other. The upsert and enqueue are "read, then write",
which is atomic on SQLite only because of `BEGIN IMMEDIATE`; on Postgres two inserts of the same key can race,
and the loser gets an `IntegrityError`. That is safe (the event retries, or the sender retries), but noisy, so
`ON CONFLICT` is the fix. Schema changes need Alembic, because `create_all` never alters a table.

**Point at:** `feedback_ingest/adapters/sqlalchemy/raw_event_queue.py` (`claim`),
`feedback_ingest/adapters/sqlalchemy/feedback_store.py` (`upsert` `ponytail:` note),
`feedback_ingest/adapters/sqlalchemy/db.py` (`assert_schema_matches`).

### Q22. How do you stop one tenant starving the others?

**Say:** Today it is first come, first served across all tenants, which I would admit up front. The fixes are a
per-tenant rate limit at the door that answers 429, and a fair claim that takes a few rows per tenant per pass.

**Go deeper:** The claim orders only by `next_attempt_at`. A fair claim ranks rows within each tenant
(`ROW_NUMBER() OVER (PARTITION BY tenant_id ...)`) and takes the first few of each; SQLite supports window
functions too. Per-tenant backlog is already visible on `/admin/queue`. Bigger customers can get their own
queue or tier. Recipe 5 in [extensions.md](extensions.md).

**Point at:** `feedback_ingest/adapters/sqlalchemy/raw_event_queue.py` (`claim`), `feedback_ingest/api/admin.py`
(`queue_counts`).

### Q23. How would you partition the data?

**Say:** `raw_events` by time, so retention is "drop last month's partition" instead of a huge delete, and by
tenant when a few tenants dominate. `feedback_records` by tenant, since every read already filters on
`tenant_id`.

**Go deeper:** That is a Postgres feature, not SQLite. Every table already carries `tenant_id`, and the record
index is `(tenant_id, source_created_at)`, so tenant partitioning does not change queries. For a customer that
needs physical separation, the path is schema-per-tenant or database-per-tenant (see
[alternatives.md](alternatives.md), "Tenancy").

**Point at:** `feedback_ingest/adapters/sqlalchemy/tables.py` (indexes and `tenant_id` columns).

### Q24. Where do analytics queries go?

**Say:** Not on this database: it is built for ingest and simple tenant-scoped reads. Big cross-source
aggregations belong in a column store like ClickHouse or BigQuery, fed from `feedback_records`.

**Go deeper:** Feed it with change data capture or a second consumer that copies records as they are written.
For incremental export you would add a "last written by us" column, because `ingested_at` is set once and
`source_updated_at` is the source's time, not ours. The JSON `metadata` maps to a JSON or map column there.

**Point at:** `feedback_ingest/adapters/sqlalchemy/tables.py` (`FeedbackRecordRow`), `feedback_ingest/api/records.py`
(the only read API today: `source_id`, `kind`, `since`, `limit`, `include_deleted`).

---

## 4. Security

### Q25. How do you verify webhooks?

**Say:** Each source has its own secret, and the sender signs the raw body with HMAC-SHA256 in an `X-Signature`
header. We check it on the raw bytes, with a constant-time compare, before we parse or store anything; a bad
signature is 401 and is never written.

**Go deeper:** HMAC is a short code made from the body and a shared secret; only someone with the secret can
make it. Order of checks: API key gives the tenant (401), the source must belong to that tenant (404), the
source must be enabled (409), then the signature (401), then "is it a JSON object" (400). An empty secret never
verifies. Gap: the default scheme has no timestamp, so a captured request could be sent again; the duplicate
key makes that harmless, and real schemes like Zendesk's sign a timestamp too.

**Point at:** `feedback_ingest/api/ingest.py`, `feedback_ingest/utils/signing.py`,
`feedback_ingest/connectors/base.py` (`default_verify_signature`).

### Q26. How are API keys stored?

**Say:** We generate a random key, show it once, and store only its sha256 hash; a request's key is hashed and
looked up by that hash. A database leak does not reveal usable keys.

**Go deeper:** Why not bcrypt: bcrypt is slow on purpose to protect weak human passwords. Our keys are 32
random bytes, which nobody can guess, and we need a fast, repeatable hash so we can find the tenant by index.
Gaps: no key rotation and no expiry yet.

**Point at:** `feedback_ingest/api/tenants.py` (`secrets.token_urlsafe(32)`), `feedback_ingest/api/deps.py`
(`current_tenant`), `feedback_ingest/utils/hashing.py` (`sha256_text`).

### Q27. How do you keep secrets out of logs?

**Say:** The webhook secret is a Pydantic `SecretStr`, which prints `**********` everywhere, and the API shows it
in clear only once, at creation. The database engine hides SQL parameter values in error messages.

**Go deeper:** Later reads of a source show `"***"`. `hide_parameters=True` means a failed insert does not print
the secret it was writing. The HTTP adapter strips any username or password from URLs in its error messages,
and source creation refuses a `base_url` with credentials in it. Honest gap: the webhook secret is plain text
in `sources.webhook_secret`, because we need it to compute the HMAC; production encrypts it at rest.

**Point at:** `feedback_ingest/domain/models.py` (`Source.webhook_secret`), `feedback_ingest/api/sources.py`
(`_view`), `feedback_ingest/adapters/sqlalchemy/db.py`, `feedback_ingest/adapters/http/httpx_client.py` (`_safe`).

### Q28. Is there personal data in the logs?

**Say:** We log ids, statuses and short error reasons, not review text. Validation errors are logged without
the input values.

**Go deeper:** Every log line carries `raw_event_id`, `tenant_id`, `source_id` and `attempts`. Two gaps to name:
an HTTP error message includes up to 200 characters of the remote reply, which reaches pull logs; and raw
payloads, which do contain names and text, are kept forever. The fix for the second is a retention purge
(recipe 7 in [extensions.md](extensions.md)).

**Point at:** `feedback_ingest/services/pipeline.py` (`_describe`), `feedback_ingest/main.py` (log format),
`feedback_ingest/adapters/http/httpx_client.py`.

### Q29. What is the bootstrap token?

**Say:** Creating a tenant needs an `X-Bootstrap-Token` header that matches a setting, compared in constant time.
It is a deliberate shortcut for the demo; production puts tenant creation behind a real operator login.

**Go deeper:** The default is `change-me`, and startup logs a warning while it is unchanged. An empty token
turns tenant creation off. Someone with the token can create tenants, but cannot read another tenant's data,
because every read is scoped by that tenant's own API key. Production would also refuse to start with the
default.

**Point at:** `feedback_ingest/api/tenants.py`, `feedback_ingest/main.py` (`_warn_about_bootstrap_token`),
`feedback_ingest/config.py`.

---

## 5. Data model

### Q30. What is one record, for each source?

**Say:** One piece of feedback as the source sees it: a Playstore review, a tweet, a Discourse post, or a whole
Intercom conversation with its messages joined into the text. `kind` is the shape (`review`, `conversation`,
`post`), not the source.

**Go deeper:** Twitter and Discourse are both `post`; "tweet" is a source, not a kind. A tweet is keyed on its
original id (the first id in `edit_history_tweet_ids`), because each edit gets a new tweet id. Intercom parts are
sorted by time and joined with blank lines; `part_count`, `tags` and `state` go to metadata. The record id is a
`uuid5` of source and external id, so it never changes.

**Point at:** `feedback_ingest/domain/models.py` (`KIND_BY_SOURCE`), `feedback_ingest/connectors/twitter.py`,
`feedback_ingest/connectors/intercom.py`, ADR-002 "What one record is".

### Q31. How do edits work?

**Say:** An edit has a new "last changed" time, so it is a new raw event, and the upsert sees a newer version
and overwrites the row. An unchanged copy has the same event id and is dropped at the door.

**Go deeper:** An update keeps the stored `id`, `source_created_at` and `ingested_at`, and stores the new
version time in `source_updated_at`. Every write must be a full snapshot of the item, never a partial change,
because the upsert replaces fields (the full-snapshot rule). Discourse pull searches by creation date, so an
edit to an old post is only seen if that window is read again.

**Point at:** `feedback_ingest/adapters/sqlalchemy/feedback_store.py` (`upsert`), ADR-002 "Update rule".

### Q32. How do deletes work?

**Say:** A delete sets `deleted_at` on the record, which is called a tombstone; reads hide it by default. It is
sticky: no later edit or replay brings the item back.

**Go deeper:** A delete applies even if it is older than the stored version; in that case only `deleted_at` is
set. `GET /v1/records?include_deleted=true` shows tombstones. Today only Discourse payloads carry a delete.
Gaps: Twitter delete events go dead (no delete shape yet), Intercom redactions go dead on purpose as
"unsupported topic", and Discourse pull cannot see deletes at all because search hides deleted posts.

**Point at:** `feedback_ingest/connectors/discourse.py` (`deleted_at`), `tests/fixtures/discourse/post_deleted.json`,
`feedback_ingest/api/records.py`.

### Q33. Why a tombstone and not a hard delete?

**Say:** "This was deleted" is a fact we want to keep, and replay must not bring the item back. If we removed the
row, replaying an older raw event would recreate it.

**Go deeper:** Deletes are raw events too, and upserts never clear `deleted_at`, so replay order does not matter.
A tombstone is not legal erasure, though: the text is still in the record and in `raw_events`. A GDPR request
needs a different flow that scrubs or hard-deletes both (recipe 7 in [extensions.md](extensions.md)).

**Point at:** `feedback_ingest/adapters/sqlalchemy/feedback_store.py` (the `deleted_at` lines), ADR-002 "Deletes".

### Q34. Why is `language` mostly null?

**Say:** On purpose: we store it when the source sends it and we do not guess. Playstore and Twitter send a
language; Discourse and Intercom do not.

**Go deeper:** Language detection is a model choice with its own accuracy problems, and it is not ingestion. It
would be a later enrichment step that fills a column, with no change to how we ingest. One trap to mention: the
upsert rewrites every field, so a detected language must live in its own column or be recomputed after each
upsert (recipe 6 in [extensions.md](extensions.md)).

**Point at:** `feedback_ingest/connectors/playstore.py` (`reviewer_language`), `feedback_ingest/connectors/twitter.py`
(`lang`), ADR-002 "Where the council clashes", item 4.

### Q35. What happens when a source changes its payload, or our metadata changes?

**Say:** New fields at the source are ignored, so additions are harmless; a missing required field sends the
event to the dead list, and after the fix we replay it. On our side, every new metadata field gets a default, so
old rows still load.

**Go deeper:** You can see this in the code: `likes`, `state` and `android_os_version` all have defaults. Pydantic
ignores unknown keys when it reads stored metadata, and a test checks that. A breaking change, like a rename,
means bumping `connector_version`, fixing the transform and replaying.

**Point at:** `feedback_ingest/domain/metadata.py`, `tests/unit/test_models.py`
(`test_metadata_ignores_unknown_keys_and_rejects_unknown_source`).

### Q36. What is `connector_version` for?

**Say:** Every connector has a `version` number, and every record it builds is stamped with it. After a transform
bug, it tells you which rows the buggy version made, so you replay just those.

**Go deeper:** All four connectors are at version 1 today, and the record refuses a version below 1. The contract
test checks the stamp matches the connector. The fix loop is: fix the transform, bump `version`, restart, replay.
The stronger form is a shadow run of the new version over stored raw events, with a diff, before switching
(recipe 9 in [extensions.md](extensions.md)).

**Point at:** `feedback_ingest/connectors/*.py` (`version: ClassVar[int] = 1`), `tests/unit/connectors/test_contract.py`.

---

## 6. Extensibility

### Q37. Walk me through adding Zendesk.

**Say:** One enum value, one metadata model, one connector file, one line in the registry, and fixtures. No route,
worker, service or table changes, and the contract tests fail until every piece exists.

**Go deeper:** The steps are: add `SourceType.ZENDESK` and its kind in `KIND_BY_SOURCE`; add `ZendeskMetadata` to
the union; write `connectors/zendesk.py` with an input model, `external_event_id`, `transform` and
`verify_signature`; add it to `_ALL`; add a normal, an edited and a malformed fixture. Exact file names are recipe
1 in [extensions.md](extensions.md). Whiteboard line for "isn't the registry just an if/else": "Yes, a dict is a
dispatch table, but it lives in one file, its keys are type-checked, and a test fails if a type is missing."

**Point at:** `feedback_ingest/connectors/registry.py`, `tests/unit/connectors/test_registry.py`,
`tests/unit/connectors/test_contract.py`.

### Q38. How do you add a new kind of feedback, like an NPS survey?

**Say:** A new kind is one enum value plus fields in metadata, and because `kind` is stored as text it needs no
migration. If everyone needs to query the score, it becomes a common column, which is a migration plus a replay.

**Go deeper:** That is where the design strains: the record is the costly extension point, the connector is the
cheap one. Also update `KIND_BY_SOURCE`, because the record checks that each source maps to its kind. The
`rating` column is 1 to 5 only, so an NPS 0 to 10 score cannot reuse it.

**Point at:** `feedback_ingest/domain/enums.py` (`FeedbackKind`), `feedback_ingest/domain/models.py`, ADR-003 ruling 9.

### Q39. What if a source needs both push and pull?

**Say:** Push or pull is a choice on the source row (`mode`), not on the connector. Both paths write the same
`raw_events` table and the same transform reads it, so Discourse already does both.

**Go deeper:** A pull connector also implements `transform`, so the webhook route accepts pull sources too, as
long as the source has a secret. The API only generates a secret for push sources, so pass `webhook_secret` when
creating a pull source that should also take webhooks. Config is split: `required_config` (Discourse needs
`base_url` in both modes) and `pull_config` (`start_after`, pull only). Creating a pull source for a type with no
puller is a 422.

**Point at:** `feedback_ingest/connectors/discourse.py`, `feedback_ingest/connectors/registry.py` (`check_source`),
`tests/api/test_push_api.py` (`test_pull_source_without_a_secret_rejects_unsigned_pushes`).

### Q40. A source signs webhooks differently. Where does that go?

**Say:** Each connector has a `verify_signature(secret, body, headers)` method that by default calls the shared
HMAC-SHA256 check. A source that signs differently overrides that one method; the algorithm belongs to the
source type, the secret belongs to the tenant's source row.

**Go deeper:** Intercom would compute HMAC-SHA1 and read `X-Hub-Signature`, stripping `sha1=`. Discourse webhooks
would strip `sha256=` from `X-Discourse-Event-Signature`. None of our four override it, because our replay script
signs fixtures with the default. One honest catch: the signature contract test signs with the default header, so
an overriding connector needs that test taught its scheme.

**Point at:** `feedback_ingest/connectors/base.py`, `feedback_ingest/connectors/playstore.py` (`verify_signature`),
`tests/unit/connectors/test_contract.py` (`test_verify_signature_accepts_signed_body_and_rejects_tampered`).

---

## 7. Process

### Q41. Did you write this?

**Say:** Not by hand, and I will be straight about it: I designed it with AI agents, AI agents wrote the code, and
other agents reviewed every phase until the reviewers had nothing left. Every big decision went through a
five-advisor council, and I have read every file, so ask me about any line.

**Go deeper:** The council verdicts are the three ADRs, with full transcripts next to them. Each phase had a
written plan before any code, then a review fleet (code review, silent-failure hunting, over-engineering review,
test coverage), then fixes, then green lint, types and tests before it was committed. Deliberate shortcuts are
marked in the code with `ponytail:` comments that name the limit and the upgrade. Offer to make a small change
live, like adding a field to a metadata model and watching the contract tests react.

**Point at:** `docs/decisions/` (ADRs and council transcripts), `docs/phases/`, `docs/PLAN.md` ("Operating model").

### Q42. What would you change with another week?

**Say:** First, Postgres with Alembic migrations and `ON CONFLICT` writes, plus the worker as its own process.
Then the operator features a real incident needs: bulk replay by source and time window, metrics and alerts,
and a retention rule for raw payloads.

**Go deeper:** In order: (1) Postgres, `SKIP LOCKED`, `ON CONFLICT`, Alembic; (2) separate worker and one
scheduler; (3) bulk replay with `source_id` and `since` filters on `/admin/raw-events` (today you loop with
`jq`); (4) counters and queue age on `/health` or `/metrics`; (5) fair claiming and a per-tenant rate limit;
(6) raw-event retention and an erasure flow; (7) webhook secret rotation with an overlap window; (8) honour
`Retry-After` and back off per source; (9) the Twitter delete branch.

**Point at:** the `ponytail:` comments (`grep -rn "ponytail:" feedback_ingest`), [extensions.md](extensions.md).

### Q43. What did you not build, and why?

**Say:** Real Playstore, Twitter and Intercom API clients (recorded fixtures stand in), language detection,
fair scheduling, retention and erasure, migrations, metrics, a UI and a Docker image. Each one is a known next
step with a written plan, and none of them changes the core shape.

**Go deeper:** Say the Playstore one before they do: Google Play has no review webhook; reviews are polled from
its API, so our fixtures stand in for that poller, and the transform is the same either way. Twitter webhooks
need a CRC handshake we did not build. Also not built from the Phase 6 plan: process counters on `/health`,
source and time filters on the dead list, and a Dockerfile.

**Point at:** `docs/PLAN.md` ("Out of scope"), `docs/phases/06_hardening_interview_pack.md`, ADR-003 context table.
