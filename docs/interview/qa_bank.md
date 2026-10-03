# Q&A bank

About 55 questions an interviewer is likely to ask, grouped by topic. Sections 1 to 7 are about the design;
section 8, "How this maps to Enterpret", compares it with Enterpret's public pages. Each one has:

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
extensibility, not on running a database. The connection string is a setting, so moving to Postgres is not a
rewrite: set `FI_DATABASE_URL`, add a driver, change three queries (claim, upsert, enqueue), add migrations.

**Go deeper:** SQLite allows one writer at a time. We make that safe with three settings on every connection:
WAL (readers keep reading while one writer writes), `busy_timeout=5000` (a writer waits up to 5 seconds instead
of failing), and `foreign_keys=ON` (so the database refuses a record whose tenant differs from its source's
tenant). The ceiling is write throughput. Past that, we move to Postgres. The exact changes are recipe 2 in
[extensions.md](extensions.md).

**Point at:** `feedback_ingest/adapters/sqlalchemy/db.py` (`make_engine`), `feedback_ingest/config.py`
(`database_url`), `docs/decisions/ADR-001-storage-and-queue.md`.

### Q2. Why is a database table your queue?

**Say:** The `raw_events` table is both the audit log and the work queue, so every payload is on disk before we
reply, and I can query it, count it per tenant, and replay any row by id. A broker gives none of that for free,
and it is a second system to run.

**Go deeper:** A worker takes work with one SQL statement that sets `status='processing'` and a lease time and
returns the rows. Retries are just a `next_attempt_at` column. Dead letters are just `status='dead'`. Replay is
an `UPDATE` back to pending. Push and pull both write here, so there is one pipeline. The table is the durable
log; the port (`RawEventQueue`) is its queue view; we never call it an outbox, because an outbox holds messages
we will send out.

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
stays inside the adapters, not the services.

**Go deeper:** The ports are tenant, source and feedback stores, the raw event queue, an HTTP client and a
clock. Services import only ports, never SQLAlchemy or httpx. The rule from the council was: a port no test
uses through its fake is a port we cannot defend. The clock port exists so lease and backoff tests do not
really sleep; say exactly that. The connector Protocol is the one that matters for extensibility. How the
adapters get in: the app builds the real ones in `wiring.py` (`sql_adapters`); tests pass fakes with
`create_app(adapters=...)`; either way, the `main.py` lifespan builds the services from what it was given.

**Point at:** `feedback_ingest/ports/`, `feedback_ingest/adapters/memory/`, `feedback_ingest/wiring.py`,
`feedback_ingest/main.py` (`create_app`, `lifespan`), `tests/adapters/test_memory.py` and
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
`feedback_ingest/utils/hashing.py`, ADR-002 "Uniqueness rule", `tests/adapters/test_sqlalchemy.py`
(`test_the_database_itself_rejects_a_duplicate_key`).

### Q7. Why does the webhook return 202 and not 200?

**Say:** 202 means "saved, not finished yet", which is exactly true: the row is committed, and the worker turns
it into a record later. If we cannot save it we return 503, so the sender retries and nothing we accepted is
lost.

**Go deeper:** A duplicate delivery also gets 202, with `"duplicate": true` and the `raw_event_id` of the row
already stored, so the sender stops retrying. Everything that fails at the door is never stored: a body over
1 MiB is 413, an unknown source is 404, a pull source is 409 (webhooks are push only), a bad signature is 401, a
disabled source is 409, and a body that is not a JSON object is 400. Processing inside the request would make
the sender wait on our transform and lose the event if we crash.

**Point at:** `feedback_ingest/api/ingest.py`, `feedback_ingest/services/ingestion.py` (`AcceptResult`),
`feedback_ingest/api/errors.py` (the 503 mapping).

### Q8. Why threads and not asyncio?

**Say:** The database layer is sync SQLAlchemy on SQLite, and mixing sync and async sessions is where the hours
go. FastAPI runs our sync endpoints in its threadpool, and the worker and scheduler are two plain background
threads.

**Go deeper:** The one async endpoint is the webhook, because it reads the raw body for the signature; it then
hands the insert to the threadpool so the event loop never waits on the database (a test checks this).
`aiosqlite` would still run SQLite on a thread underneath. Our transforms are light, so the GIL is not the
limit. If transforms got heavy, the answer is a separate worker process, not asyncio. The real limit to admit:
Starlette's threadpool is 40 threads, and `POST /sync` runs a whole sync inline (up to the 60 s deadline), so 40
concurrent syncs would stall every sync route behind them. The `ponytail:` note on `api/sync.py` says to enqueue
a sync job once backfills take minutes.

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

**Point at:** `feedback_ingest/connectors/base.py` (`new_record`), `feedback_ingest/adapters/sqlalchemy/raw_event_queue.py`
(`enqueue`), `feedback_ingest/adapters/sqlalchemy/feedback_store.py` (`upsert`).

---

## 2. Failure modes

Detailed symptoms for each are in [failure_scenarios.md](failure_scenarios.md).

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
the event dead without running the transform. Why `>` in that pre-check but `>=` in the retry path:
the claim already counted the attempt about to start, so attempt 5 still runs (`5 > 5` is false); after a
transient failure, `attempts >= max_attempts` means that was the last allowed try, so the event goes dead
instead of scheduling a sixth. A slow worker that comes back after its lease ran out is
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
event and is not dropped. Demo step 3 shows this live. One case warns: if the stored copy is already dead, the
duplicate leaves it dead. We log a WARNING, `duplicate of a dead raw event; left dead, replay it`, and
the operator replays it. Re-running it automatically would be pointless: a byte-identical duplicate cannot carry
a fix; only a connector change can, so replay after a version bump.

**Point at:** `feedback_ingest/services/ingestion.py`, `feedback_ingest/connectors/playstore.py`
(`external_event_id`), `tests/e2e/test_push_to_query.py`, `tests/unit/services/test_ingestion.py`
(`test_a_duplicate_of_a_dead_event_is_not_replayed_but_warns`).

### Q14. What if an older edit arrives after a newer one?

**Say:** The upsert compares "when did this version last change" on both sides, and an older version loses. So a
late, stale copy is stored in `raw_events` and marked processed, but it does not overwrite the record.

**Go deeper:** "Last changed" is `source_updated_at`, or `source_created_at` when a source sends no update
time. Say this one: Play payloads carry no creation time, so a review's `source_created_at` is the first-seen
`lastModified`. Equal or newer wins, so a re-run of the same version, like a replay, still writes. The store returns
`skipped_older` for the loser. A delete is the exception: it always applies, even if it is older. A contract
test feeds every connector's edit fixtures in both orders and checks the newer text wins.

**Point at:** `feedback_ingest/domain/models.py` (`merge`, `version_at`), both feedback stores (`upsert` calls `merge`), `tests/unit/connectors/test_contract.py` (`test_an_edit_is_a_new_raw_event_and_the_newer_text_wins`).

### Q15. What about a poison payload?

**Say:** A payload that fails its Pydantic input model, or raises `PermanentError`, goes to `dead` on the first
attempt with a short reason. It is never retried and never thrown away, so after a fix we replay it.

**Go deeper:** The error is written as `field: message` pairs without the input values, capped at 500
characters, so customer text does not reach logs or the `error` column. The raw row is still stored, because
`external_event_id` never raises: it falls back to a payload hash. A Play Store review with no user comment is
also dead, with `review has no user comment`, so a bad payload never looks like "no data". Demo step 7 replays a
bad payload and shows it go dead again, which proves replay really re-runs it.

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

**Go deeper:** Be precise about what that test proves. SQLite serialises writers, so it shows the statement
never double-claims with real threads and engines; it does not exercise Postgres. What keeps claims safe on
Postgres READ COMMITTED is the repeated predicate: an `UPDATE` that waited on a row lock re-checks its `WHERE`
against the new row version, sees `processing`, and skips the row. This happens by accident with `uvicorn --workers N`, which starts N copies of the in-process
worker. The fence stops a late finish from overwriting a newer one. N copies also start N schedulers, which
fetch the same pages; that wastes calls but the unique key drops the repeats. Inside one process, a source
syncs once at a time: a second manual sync of it gets 409, and the scheduler skips it while a manual sync runs.
On Postgres, the claim adds `FOR UPDATE SKIP LOCKED`. Never say that runs today.

**Point at:** `feedback_ingest/adapters/sqlalchemy/raw_event_queue.py` (`claim` and its `ponytail:` note),
`tests/adapters/test_sqlalchemy.py` (`test_concurrent_claims_are_disjoint`), `feedback_ingest/services/pull.py`
(the per-source lock), `tests/unit/services/test_pull_concurrency.py`.

### Q18. What if Discourse rate-limits us while we pull?

**Say:** The HTTP adapter turns a 429 into a `TransientError`, the pull stops, and the pages already fetched stay
saved. The cursor does not move, so the next tick starts from the same bookmark and the repeats are dropped.

**Go deeper:** 408, 429, 5xx, network errors and the 10-second timeout are all transient; other 4xx are
permanent. Two caps stop a runaway pull: one sync has 60 seconds in total (`FI_PULL_DEADLINE_SECONDS`), and one
reply may be at most 2,000,000 bytes (`FI_HTTP_MAX_BYTES`); both are transient. The adapter follows no
redirects. The manual sync answers 502 with `"error": "429 from …/search.json"` in the result. `/health` counts
the source in `failing_sources` after a failed scheduled tick; it is a count only, because health has no auth,
and it does not change the status code. The Discourse cursor only moves on the final page of a run, because
search results are not guaranteed oldest first. Gaps to admit: we do not read `Retry-After`, and the scheduler
does not back off per source; it just tries again every 300 seconds.

**Point at:** `feedback_ingest/adapters/http/httpx_client.py`, `feedback_ingest/services/pull.py` (`sync`),
`feedback_ingest/connectors/discourse_pull.py`, `tests/unit/services/test_pull_failures.py`,
`tests/unit/connectors/test_discourse_pull_limits.py`, `tests/adapters/test_httpx_client.py`.

### Q19. The pull cursor is stuck. Why?

**Say:** Four causes: a repeated error like a 429, a window too busy to reach its last page within 10 pages, a
bad config, or the scheduler is not running or the source is disabled. `/health` counts the source in
`failing_sources` when its last scheduled sync failed (the log line names it), and a manual sync shows the reason: it answers 502 with
the error in the result.

**Go deeper:** A window that needs more than 10 search pages (Discourse refuses page 11) stops after page 10
with the cursor unchanged, so the result shows `pages: 10` and an `error` that says `window exceeds 10 pages`.
Ten pages is about 500 posts, so about 500 posts per day is the hard limit of Discourse search. The fix is a
smaller `window_days` (1 to 31): `PATCH /v1/sources/{id}` with `{"config": {"window_days": "1"}}`. The PATCH
merges that key into the stored config and checks the result, so a bad value is 422. A dead scheduler shows
`scheduler_alive: false` and health 503.
The PDF sample search response omits `grouped_search_result`; the live API always sends it and we require it so
a missing one is never read as the last page; a mock built from the PDF sample fails loudly, not silently.
Moving the cursor back by hand is always safe because repeats are dropped; moving it forward skips posts. The
step-by-step is Runbook 2 in [firefight_runbook.md](firefight_runbook.md).

**Point at:** `feedback_ingest/connectors/discourse_pull.py` (`_MAX_PAGES`), `feedback_ingest/api/sync.py`,
`feedback_ingest/api/sources.py` (the PATCH route), `feedback_ingest/api/health.py`,
`tests/api/test_source_updates.py` (`test_patch_merges_config_and_checks_the_result`).

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

**Say:** Set `FI_DATABASE_URL`, add a driver, change three queries (claim, upsert, enqueue), add migrations. The
claim subquery gets `.with_for_update(skip_locked=True)`, the upsert and enqueue move to
`INSERT ... ON CONFLICT`, and the SQLite pragmas only run for SQLite.

**Go deeper:** The claim's `ponytail:` comment marks the spot. `SKIP LOCKED` means "skip rows another
transaction has locked", so workers do not wait on each other. The upsert and enqueue are "read, then write",
which is atomic on SQLite only because of `BEGIN IMMEDIATE`; on Postgres two inserts of the same key can race,
and the loser gets an `IntegrityError`. That is safe (the event retries, or the sender retries), but noisy, so
`ON CONFLICT` is the fix. Schema changes need Alembic, because `create_all` never alters a table. What else is SQLite-specific: only the
two `event.listens_for` hooks in `db.py` (pragmas and `BEGIN IMMEDIATE`), already behind a dialect check;
`RETURNING`, the JSON column and the schema inspector all work on Postgres.

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
make it. There is no API key on this route, because a real sender cannot add ours: the source id picks the
source, and its HMAC proves the sender. Order of checks: the source by its unguessable id (404); only push
sources take webhooks, so a pull source is 409; then the signature (401); then "is the source enabled" (409),
asked after the signature so only a caller who proved itself learns the state; then "is it a JSON object" (400).
A body over 1 MiB is 413 before any of this. The tenant comes from the source row. Gap: the default scheme has
no timestamp, so a captured request could be sent again; the duplicate key makes that harmless, and real schemes
like Zendesk's sign a timestamp too.

**Point at:** `feedback_ingest/api/ingest.py`, `feedback_ingest/utils/signing.py`,
`tests/unit/test_utils.py` (`test_hmac_matches_rfc_4231_case_2`, a published HMAC test vector),
`feedback_ingest/connectors/base.py` (`default_verify_signature`), `tests/api/test_push_api.py`
(`test_only_push_sources_take_webhooks_and_the_signature_is_checked_before_state`).

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

**Go deeper:** Every line ends with the same four keys: `raw_event_id`, `tenant_id`, `source_id`, `attempts`.
Every worker and pipeline line about an event fills in `raw_event_id`; pull lines fill in `source_id` and
`tenant_id`; lines with no event, like startup, show `-`. A newline in a message is written as `\n`, so a payload
cannot fake a second log line. HTTP errors carry only the status and the URL, never the reply body; Discourse's
own search error text goes only to a WARNING line, not to the sync result. The gap to name: raw payloads, which
do contain names and text, are kept forever. The fix is a retention purge (recipe 7 in
[extensions.md](extensions.md)).

**Point at:** `feedback_ingest/services/pipeline.py` (`_describe`, `event_extra`), `feedback_ingest/main.py`
(`OneLineFormatter`), `feedback_ingest/adapters/http/httpx_client.py`, `tests/api/test_webhook_limits.py`
(`test_log_lines_cannot_be_split_by_injected_newlines`).

### Q29. What is the bootstrap token?

**Say:** Creating a tenant needs an `X-Bootstrap-Token` header that matches a setting, compared in constant time.
It is a deliberate shortcut for the demo; production puts tenant creation behind a real operator login.

**Go deeper:** The default is `change-me`. While the token is the default or empty, the route refuses every
call with 401, and startup logs the WARNING `POST /admin/tenants is refused: set FI_BOOTSTRAP_TOKEN`.
`scripts/demo.sh` exports a random `FI_BOOTSTRAP_TOKEN` before it starts the server, and `seed.py` exits unless
it is set. Someone with the token can create tenants, but cannot read another tenant's data, because every read
is scoped by that tenant's own API key.

**Point at:** `feedback_ingest/api/tenants.py`, `feedback_ingest/main.py` (the warning in `lifespan`),
`feedback_ingest/config.py` (`bootstrap_open`), `tests/api/test_tenants_api.py`
(`test_the_default_or_an_empty_token_refuses_bootstrap`).

---

## 5. Data model

### Q30. What is one record, for each source?

**Say:** One piece of feedback as the source sees it: a Playstore review, a tweet, a Discourse post, a whole
Intercom conversation with its messages joined into the text, or one entry of a custom webhook batch. `kind` is
the shape (`review`, `conversation`, `post`, `survey`), not the source.

**Go deeper:** Twitter and Discourse are both `post`; "tweet" is a source, not a kind. A tweet is keyed on its
original id (the first id in `edit_history_tweet_ids`), because each edit gets a new tweet id. Intercom parts are
sorted by time and joined with blank lines; `part_count`, `tags` and `state` go to metadata. A custom record's
kind comes from its own `type` (`KIND_BY_RECORD_TYPE`), because one custom source can send all four kinds. The
record id is a `uuid5` of source and external id, so it never changes.

**Point at:** `feedback_ingest/domain/enums.py` (`KIND_BY_SOURCE`, `KIND_BY_RECORD_TYPE`), `feedback_ingest/connectors/twitter.py`,
`feedback_ingest/connectors/intercom.py`, ADR-002 "What one record is".

### Q31. How do edits work?

**Say:** An edit has a new "last changed" time, so it is a new raw event, and the upsert sees a newer version
and overwrites the row. An unchanged copy has the same event id and is dropped at the door.

**Go deeper:** An update keeps the stored `id`, `source_created_at` and `ingested_at`, and stores the new
version time in `source_updated_at`. For Play Store that means `source_created_at` is the first-seen
`lastModified`, because Play payloads carry no creation time; say so if asked. Every write must be a full snapshot of the item, never a partial change,
because the upsert replaces fields (the full-snapshot rule). Discourse pull searches by creation date, so an
edit to an old post is only seen if that window is read again.

**Point at:** `feedback_ingest/domain/models.py` (`merge`), `feedback_ingest/connectors/playstore.py`, ADR-002 "Update rule".

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

**Go deeper:** All five connectors are at version 1 today, and the record refuses a version below 1. The contract
test checks the stamp matches the connector. The fix loop is: fix the transform, bump `version`, restart, replay.
The stronger form is a shadow run of the new version over stored raw events, with a diff, before switching
(recipe 9 in [extensions.md](extensions.md)).

**Point at:** `feedback_ingest/connectors/*.py` (`version: ClassVar[int] = 1`), `tests/unit/connectors/test_contract.py`.

---

## 6. Extensibility

### Q37. Walk me through adding Zendesk.

**Say:** Five steps: an enum value, a metadata model, a connector file, a registry entry, and fixtures. No route,
worker, service or table changes, and the tests fail until every piece exists. The `custom` connector was added
exactly this way, so it is the worked example.

**Go deeper:** The steps are: (1) add `SourceType.ZENDESK` and its kind in `KIND_BY_SOURCE`, both in `domain/enums.py`,
reusing an existing kind; (2) add `ZendeskMetadata` to the `SourceMetadata` union in
`domain/metadata.py`; (3) write `connectors/zendesk.py` with its input model, `source_type`, `version`,
`required_config`, `external_event_id`, `transform` (built with `new_record`) and `verify_signature`; (4) add it
to the tuple inside `CONNECTORS` in `connectors/registry.py` (and to `PULLERS` if it pulls); (5) add fixtures
under `tests/fixtures/zendesk/`, at least `malformed.json`. `test_registry.py` and
`test_every_source_type_has_a_metadata_model` fail until all of it exists; then the contract tests run every
fixture. Exact file names are recipe 1 in [extensions.md](extensions.md). Where it strains is `kind`: it is the one cross-cutting field. Since
`kind` became a plain field that `new_record` fills from `KIND_BY_SOURCE`, a new source touches only its own
files plus the enum and the metadata union. Whiteboard line for "isn't the
registry just an if/else": "Yes, a dict is a dispatch table, but it lives in one file, its keys are
type-checked, and a test fails if a type is missing."

**Point at:** `feedback_ingest/connectors/registry.py`, `feedback_ingest/connectors/custom.py` (the worked
example), `tests/unit/connectors/test_registry.py`, `tests/unit/test_models.py`
(`test_every_source_type_has_a_metadata_model`), `tests/unit/connectors/test_contract.py`.

### Q38. How do you add a new kind of feedback, like an NPS survey?

**Say:** We did it: `survey` is a real kind now. It was one enum value, `FeedbackKind.SURVEY`, plus a place for
the score in metadata, and because `kind` is stored as text it needed no migration. If everyone needs to query
the score, it becomes a common column, which is a migration plus a replay.

**Go deeper:** That is where the design strains: the record is the costly extension point, the connector is the
cheap one. `kind` is a plain field that `new_record` fills from the source type through `KIND_BY_SOURCE`; only `custom`
records pass their own, from their `type` through `KIND_BY_RECORD_TYPE`, where `SURVEY` maps to `survey`. The score lives in
`CustomMetadata.score`, because the `rating` column is 1 to 5 only, so an NPS 0 to 10 score cannot reuse it.

**Point at:** `feedback_ingest/domain/enums.py` (`FeedbackKind`), `KIND_BY_RECORD_TYPE` in the same file, `feedback_ingest/domain/metadata.py` (`CustomMetadata`), ADR-003 ruling 9.

### Q39. What if a source needs both push and pull?

**Say:** Push or pull is a choice on the source row (`mode`), not on the connector. Both paths write the same
`raw_events` table and the same transform reads it, so a Discourse source can be either. For both at once, you
create two sources: one push, one pull.

**Go deeper:** Webhooks are push only. A pull source never takes a webhook (409), and creating a pull source with
a `webhook_secret` is a 422. A push source always has a secret: the API generates one if you give none. Config
is split: `required_config` (Discourse needs `base_url` in both modes) and `pull_config` (`start_after`, pull
only). Creating a pull source for a type with no puller is a 422. Two sources means two `source_id`s, so the same
post arriving both ways becomes two records; that is the cost of keeping one mode per source.

**Point at:** `feedback_ingest/connectors/discourse.py`, `feedback_ingest/connectors/registry.py` (`check_source`),
`feedback_ingest/api/schemas.py` (`SourceCreate`), `tests/api/test_push_api.py`
(`test_only_push_sources_take_webhooks_and_the_signature_is_checked_before_state`).

### Q40. A source signs webhooks differently. Where does that go?

**Say:** Each connector has a `verify_signature(secret, body, headers)` method that by default calls the shared
HMAC-SHA256 check. A source that signs differently overrides that one method; the algorithm belongs to the
source type, the secret belongs to the tenant's source row.

**Go deeper:** Intercom's public docs describe HMAC-SHA1 in `X-Hub-Signature` (prefixed `sha1=`), so its
override would compute that. Discourse webhooks
would strip `sha256=` from `X-Discourse-Event-Signature`. None of our five changes the scheme: each one calls
the default, because our sign script (`scripts/sign.py`, secret from `FI_SIGN_SECRET`) signs fixtures with it. One honest catch: the signature contract test signs with the default header, so
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
Then the operator features a real incident needs: a time window on bulk replay, metrics and alerts, and a
retention rule for raw payloads.

**Go deeper:** In order: (1) Postgres, `SKIP LOCKED`, `ON CONFLICT`, Alembic; (2) separate worker and one
scheduler; (3) a `since` filter on bulk replay (bulk replay by `source_id` and `status` is built:
`POST /admin/raw-events/replay`); (4) counters and queue age on `/health` or `/metrics`; (5) fair claiming and a per-tenant rate limit;
(6) raw-event retention and an erasure flow; (7) webhook secret rotation with an overlap window; (8) honour
`Retry-After` and back off per source; (9) the Twitter delete branch.

**Point at:** the `ponytail:` comments (`grep -rn "ponytail:" feedback_ingest`), [extensions.md](extensions.md).

### Q43. What did you not build, and why?

**Say:** Real Playstore, Twitter and Intercom API clients (recorded fixtures stand in), language detection,
fair scheduling, retention and erasure, migrations, metrics, a UI and a Docker image. Each one is a known next
step with a written plan, and none of them changes the core shape.

**Go deeper:** Say the Playstore one before they do: Google Play has no review webhook, so our fixtures stand in
for that poller. The full list, with the reason for each and the items kept on purpose, is one list:
[README § What is deliberately not built](../../README.md#what-is-deliberately-not-built).

**Point at:** that README section, [debt_ledger.md](debt_ledger.md) for the `ponytail:` shortcuts.

---

## 8. How this maps to Enterpret

Everything here about Enterpret comes from their public pages, collected in
[docs/research/](../research/00_tailoring_decisions.md). Say "their public docs describe" or "their engineering
blog says". Never say "they do X internally": we do not know their internals.

### Q44. Where does this sit in Enterpret's Unify, Understand, Act flow?

**Say:** Their home page describes the product as three steps: Unify, then Understand, then Act. This service is
the Unify step: it takes feedback in from many sources and turns each item into one normalised Feedback Record.

**Go deeper:** Understand is their taxonomy (Keywords, Themes and Categories; "Reasons" is the older name) and
Wisdom, their question answering; it would read our records downstream. Act (Slack, Jira and similar) is further
downstream again. We built neither, and I would say so.

**Point at:** `feedback_ingest/domain/models.py` (`FeedbackRecord`), `docs/research/01_product_and_integrations.md`
(section 1).

### Q45. How does your custom connector compare with their public webhook?

**Say:** Their help center describes `POST /webhook/custom/all`: a batch `{"records": [...]}` where each record
has `id`, `type`, `createdAt` in epoch seconds, and metadata. Our `custom` connector takes that envelope on our
normal route, `POST /v1/sources/{id}/events`, and makes one Feedback Record per entry.

**Go deeper:** One push is one raw event, keyed by the hash of the whole batch; each record then upserts on
(source id, record id) with the version guard. We take a simpler shape than theirs: a flat `text` and flat
metadata values, where their docs describe content blocks per type and typed metadata arrays. One unsupported
`type` sends the whole batch dead; the `ponytail:` note says to split a batch into one raw event per record if
senders need partial acceptance.

**Point at:** `feedback_ingest/connectors/custom.py`, `tests/fixtures/custom/batch.json`,
`tests/api/test_custom_webhook.py` (`test_a_custom_batch_is_one_delivery_and_three_records_of_three_kinds`), demo
step 6.

### Q46. Why HMAC per source instead of their `api-key` header?

**Say:** Their docs describe an `api-key` header, one key per webhook integration. Our webhook takes no API key:
the source id in the URL picks the source, and an HMAC-SHA256 signature of the raw body, made with that source's
secret, proves the sender.

**Go deeper:** A signature also proves the body was not changed on the way, which a key in a header does not.
Senders like Intercom already sign their webhooks with an HMAC, though with their own header and hash; each connector's `verify_signature` hook is where that exact check goes (every connector uses our SHA-256 `X-Signature` default today). The cost: the sender must
compute a hash, which is harder for a quick script than pasting a key.

**Point at:** `feedback_ingest/api/ingest.py`, `feedback_ingest/utils/signing.py`, `tests/api/test_push_api.py`
(`test_no_api_key_is_needed_but_a_signature_is`).

### Q47. What does 202 mean here, compared with their "accepted does not mean processed"?

**Say:** The same idea. Their webhook docs say a 200 means accepted, not processed; our 202 means the raw payload
is committed to `raw_events`, and the worker builds the records later.

**Go deeper:** We picked 202 because that code means "accepted for processing". If we cannot save, we answer 503
so the sender retries; we never say yes to something that is not on disk. The gap: the sender cannot ask about
one delivery's outcome; only the tenant can, with `GET /admin/raw-events/{id}`.

**Point at:** `feedback_ingest/api/ingest.py`, `feedback_ingest/services/ingestion.py`, `tests/api/test_push_api.py`
(`test_storage_down_is_503_never_202_and_logged`).

### Q48. How do you handle a repeated id, compared with their skip by default and opt-in replace?

**Say:** Their docs describe two modes: by default a repeated `id` is skipped, and "mutability", which their
support turns on, makes a repeated `id` replace the record. We have both, at two layers: an identical delivery is
skipped at `raw_events`, and an equal or newer version of a record replaces it in `feedback_records`; an older one
never does.

**Go deeper:** For the custom connector, the same batch sent twice has the same hash, so it is a duplicate. A
batch that changes one record is a new raw event, and each record in it goes through the version guard. We did
not copy their toggle: newer always wins and older always loses.

**Point at:** `feedback_ingest/adapters/sqlalchemy/feedback_store.py` (`upsert`), `feedback_ingest/connectors/custom.py`
(`external_event_id`), `tests/fixtures/custom/batch_edited.json`.

### Q49. How does your version guard compare with what their engineering blog describes?

**Say:** Their engineering blog (the KOSH post) says stale or out-of-order updates are rejected by version, so
they never overwrite newer data. Ours is the same rule in one place: the upsert compares `source_updated_at` (or
`source_created_at`), keeps the newer, and reports `skipped_older` for the loser.

**Go deeper:** An equal version is accepted, so a replay writes the same row again. Deletes are sticky, so replay
order does not matter. The limit: our version is the source's own timestamp, so two edits with the same
timestamp are ordered by whichever we process last.

**Point at:** `feedback_ingest/adapters/sqlalchemy/feedback_store.py` (`upsert`), `feedback_ingest/domain/models.py`
(`version_at`), `tests/unit/connectors/test_contract.py` (`test_an_edit_is_a_new_raw_event_and_the_newer_text_wins`).

### Q50. How would you handle noisy neighbours and queue clogging here?

**Say:** A noisy neighbour is one tenant whose load slows everyone else; queue clogging is bad or huge items
blocking the queue. Their engineering blog names both as incidents and says they partition events by tenant and
object type.

**Go deeper:** Clogging by bad items is handled here: a bad payload goes dead on the first try and leaves the
queue, a payload that crashes the process is dead once its attempts pass 5, and a body over 1 MiB is refused with 413.
Noisy neighbours are not: the claim is first come, first served across tenants, and only the per-tenant counts on
`GET /admin/queue` show it. The fixes, in order: a per-tenant limit at the door, a fair claim, then a queue per
tenant (recipe 5 in [extensions.md](extensions.md)).

**Point at:** `feedback_ingest/adapters/sqlalchemy/raw_event_queue.py` (`claim`), `feedback_ingest/services/pipeline.py`,
`feedback_ingest/api/body_limit.py`.

### Q51. Where would ClickHouse fit?

**Say:** Their engineering blog describes ClickHouse as an analytics projection, meaning a copy of the data shaped
for big aggregate reads, fed by change data capture. Here it would sit after `feedback_records`: this database
keeps ingest and simple tenant-scoped reads, and cross-source counts and trends move to the column store.

**Go deeper:** We built none of it. The first thing to add is a "last written by us" column on records, so an
incremental copy can ask what changed since last time. The rest is Q24.

**Point at:** `feedback_ingest/adapters/sqlalchemy/tables.py` (`FeedbackRecordRow`), Q24.

### Q52. Why no PII redaction, when their docs say they scrub before ingestion?

**Say:** Their platform page says PII such as card numbers and SSNs is detected and obfuscated before ingestion.
We did not build that; we only keep customer text out of logs and error messages.

**Go deeper:** It would go in `IngestionService.accept`: compute the duplicate key from the original payload,
replace emails, phones and card numbers with placeholders like `[EMAIL]`, then enqueue. It must run before
storage, because `raw_events` keeps every payload as received. The trade-off: once raw is redacted, replay can
never get the original text back.

**Point at:** `feedback_ingest/services/ingestion.py`, `feedback_ingest/services/pipeline.py` (`_describe`), recipe 6
in [extensions.md](extensions.md).

### Q53. Why a 5-minute poll, when their help center says every 4 hours?

**Say:** Their help center pages for Intercom, Front and the two app stores describe a pull every 4 hours. Our
interval is a setting, `FI_PULL_INTERVAL_SECONDS`, with a default of 300 seconds so the demo shows results fast.

**Go deeper:** A tick re-reads its whole window and the unique key drops repeats, so a short interval costs
upstream calls, not correctness. It is one global value today; production would set it per source. Their pages
also say support tools ingest resolved conversations only; we take every `conversation.*` snapshot, so a
conversation updates each time it changes.

**Point at:** `feedback_ingest/config.py` (`pull_interval_seconds`), `feedback_ingest/services/scheduler.py`,
`feedback_ingest/connectors/intercom.py`.

### Q54. Why no rate limit, and why not their 200 KB and 100-record limits?

**Say:** Their webhook page lists a 200 KB request cap, about 100 records per batch, and a request-rate limit. We
have one size limit, 1 MiB on every route (413), no record count cap and no rate limit.

**Go deeper:** A rate limit is the first noisy-neighbour fix: a per-tenant check at the door that answers 429
(recipe 5 in [extensions.md](extensions.md)). A record cap would be one `max_length` on the batch model, but then
an oversized batch goes dead after its 202 instead of being refused at the door.

**Point at:** `feedback_ingest/api/body_limit.py`, `tests/api/test_webhook_limits.py`
(`test_a_body_over_the_limit_is_413_declared_or_streamed`), `feedback_ingest/connectors/custom.py` (`CustomBatchIn`).

### Q55. Why is SURVEY a kind, and AUDIO_RECORDING rejected?

**Say:** Their webhook docs list five record types: REVIEW, CONVERSATION, FORUM_CONVERSATION_THREAD, SURVEY and
AUDIO_RECORDING. We map the first four to kinds (`review`, `conversation`, `post`, `survey`), and added `survey`
because no existing kind fit.

**Go deeper:** AUDIO_RECORDING is not text: it needs an audio download and a transcript, which is enrichment, not
ingestion. Today it is a `PermanentError`, and since one push is one raw event, the whole batch goes dead and can
be replayed after a fix.

**Point at:** `feedback_ingest/domain/enums.py` (`KIND_BY_RECORD_TYPE`), `tests/unit/connectors/test_custom.py`
(`test_an_unsupported_type_or_an_empty_batch_goes_dead`), `tests/fixtures/custom/unsupported_type.json`.
