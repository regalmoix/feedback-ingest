# Study notes

Points from my own Q&A while learning the code: interview-relevant or non-obvious only. Short answers,
small examples. Newest at the bottom of each section.

## Design choices

**Can we swap the database, HTTP client or queue?**
Yes, within the port's promises. Services only call port methods, so a swap is one new adapter. Proof:
every store and queue port already has two implementations (SQLite and in-memory) passing the same
contract tests. SQLite to Postgres is easy. Table queue to Kafka is harder: the port promises "find event
by id" and "retry this one message later", which Kafka does not do natively, so the adapter must build
that or the port changes.

**Protocol vs abstract base class (ABC)?**
Both work. A Protocol is like a Java interface, but a class matches by having the right methods
("duck typing"); declaring it is optional. Chosen because test fakes need no inheritance and there is no
runtime machinery (mypy checks before the code runs). Every implementation still names its Protocol
(`class SqlSourceStore(SourceStore)`) so the IDE can jump to implementations and mypy flags drift at the
class line.

**Why random ids for tenants and sources instead of readable ones (like a domain)?**
Ids must never change and they are copied into every row; names and domains change, one company can own
several domains, and a random id in a URL leaks nothing. The readable label is the unique `name`
(`lumenote`). A readable "slug" could be added as a second unique column for nicer URLs.

**Why poll the queue every second instead of being notified?**
Simple and cannot lose work: the table is the truth. Cost: up to 1 s delay when idle. Upgrades, simplest
first: wake the worker in-process when an event is saved; Postgres LISTEN/NOTIFY; pub/sub (SNS, SQS,
Kafka); SQS in front of AWS Lambda. A notification is only a hint, so keep a slow poll as a safety net.
Lambda trade-offs: cold starts, a concurrency cap that can hammer the database, cost at steady volume.
(Their public engineering blog mentions Lambda and Step Functions.)

## Sources and auth

**What is a Source?**
One configured connection for one tenant: `type` (playstore, discourse, ...), `mode` (push = they call our
webhook, pull = we poll them), `config` (per-type settings), `webhook_secret`, `cursor`, `enabled`. A
tenant can have several sources of one type (two Play Store apps = two rows, different ids).

**How does the webhook secret work?**
It is shared between us and the sender, not private to us. We generate it when the source is created and
show it once. The sender signs each body with it (HMAC-SHA256, `X-Signature` header); we recompute and
compare. Wrong or missing signature: 401. Only push sources have one.

**Why does the webhook take no API key?**
Senders like Intercom can only be given a URL, not custom headers. The unguessable source id in the URL
picks the source, its signature proves the sender, and the tenant comes from the source row.

**Why store only a hash of the API key? Why plain SHA-256, not bcrypt?**
A leaked database must not let anyone log in. The key is shown once at tenant creation; we store only its
SHA-256 hash, and on each request hash the `X-API-Key` header and look that hash up (unique index). Plain
fast hash is fine because keys are 256 random bits (unguessable); passwords are short and guessable, so
they need slow salted hashes (bcrypt, argon2), which also could not be looked up directly. Contrast:
webhook secrets are stored in plain text because we need the real value to compute each HMAC; the fix
is encryption at rest or a secrets manager (KMS), the "secrets at rest" gap.

**Do we authenticate when we pull from Discourse?**
No: meta.discourse.org search is public. A private forum needs an API key in request headers; not built
(known gap). It would live with the source's settings, stored as a secret.

**What is `config` for?**
Per-type settings, not only for pull. Discourse needs `base_url` in both modes (to build post links); pull
also needs `start_after` and `window_days`. Play Store, Twitter, Intercom, custom: usually `{}`.

**What is the cursor?**
A bookmark of how far a pull source has read. With `start_after=2021-01-01`, `window_days=4`: first sync
reads 01-01..01-05 and the cursor becomes `2021-01-05T00:00:00`; next sync reads 01-05..01-09. If a sync
fails halfway, the cursor does not move and the window is re-read. A window reaching today ends at "newest
post minus 60 s": read a post twice rather than miss one; duplicates are dropped.

## The push path

**Webhook check order?**
Body over 1 MiB 413 (middleware, before the route) → source not found 404 → not a push source / no secret
409 → bad signature 401 → disabled 409 (after the signature, so only a proven sender learns it) → not a
JSON object, NaN or absurd nesting 400 → save → 202.

**Does the 202 wait for the save?**
Yes. `await run_in_threadpool(...)` waits; the thread only keeps the server free for other requests while
the blocking database write runs. 202 means "saved, not yet processed"; the worker turns it into a record
seconds later. If the database is down we answer 503 and never 202, so the sender retries.

**What does the sender do with the response?**
Mostly reads the status code: 2xx stop, 5xx retry, 4xx give up or alert. The body (`raw_event_id`,
`duplicate`) is for us and custom senders, e.g. look the id up in `/admin/raw-events/{id}`.

**`external_id` vs `external_event_id` vs our `id`?**
`external_id` is the source's own id for the item (like an ATS candidate id): `r1`. `external_event_id` is
that item at a version: Play Store `r1:<lastModified>`; it is the dedupe key for deliveries. Our `id` is
the internal unique key (external ids can clash across sources). A resend has the same key and is
dropped; an edit has a new time, so a new key, so it is kept and later updates the record. If the key were
only `r1`, edits would be lost. Exceptions: a custom batch is keyed by a hash of the whole body (the batch
is one delivery); an unreadable payload falls back to a body hash.

## The pull path

**Who starts a pull?**
Two callers, one function (`PullService.sync`). The scheduler thread, every 5 minutes, for every enabled pull
source. Or a tenant by hand: `POST /v1/sources/{id}/sync` with their own API key (not an admin route). The
manual call runs inline and answers with the result: 200, or 502 if the source API failed, or 409 if the
source is not an enabled pull source or is already syncing.

**Can two syncs of one source run at once?**
No, in one process: a per-source lock, and the second caller gets 409. Across processes (`uvicorn --workers
N`) the lock is not shared, so Discourse can be polled twice. Harmless (duplicates are dropped by the unique
key), just wasted calls. Fix: a DB lease on the source row, like the event claim:
`UPDATE sources SET sync_lease_until = now + 90s WHERE id = :id AND (sync_lease_until IS NULL OR
sync_lease_until < now) RETURNING id`. One row back = yours, zero = 409. Atomic across processes, expires if a
process crashes, no new infrastructure. Lease longer than the 60 s pull deadline. Redis `SET NX PX` works too
but adds a server just for a lock; Postgres `pg_try_advisory_lock` is simple but holds a connection for the
whole sync. Correctness is already safe (`max()` cursor, unique key); the lease only saves wasted calls.

**When does the cursor move?**
After the page's payloads are saved, never before, and never backwards (`max(stored, new)`). Discourse moves
it only on the final page of a window, so a crash mid-window re-reads that window; duplicates are dropped.
Why only the final page: Discourse search is not guaranteed oldest-first. If page 1 (posts from 02-05) moved
the cursor and we crashed before page 2 (a post from 02-02), the next sync would start after 02-05 and never
read 02-02. Cost: a window over 10 pages (~500 posts) never reaches its final page, so the cursor is stuck until
`window_days` is lowered with one PATCH. A source whose API returns results in time order could move it per page;
the generic `_sync` loop already allows that.
Same trap with the 60 s deadline: if a window always needs longer, every sync times out mid-window, saves
pages as duplicates, and the cursor never moves (quieter than the 10-page error). Signs: the source stays in
`failing_sources`, duplicates grow, cursor flat. Fix: smaller `window_days`, or a bigger deadline; real fix is
paging by time inside the window or saving "window X, page N done" to resume.

**Scheduler in prod: cron or Airflow?**
Split it. A tiny trigger (cron, EventBridge, Celery beat) runs every minute, picks sources with
`next_sync_at <= now`, and enqueues one sync job per source. Sync workers run the jobs in parallel, so a slow
source delays only itself (today one thread ticks every source in turn). A lease on the source row stops
double pulls (manual plus scheduled, or two workers). Per-source schedules also give per-source intervals,
backoff for sources that keep failing, and room for each API's rate limits. Airflow suits a few big batch jobs
(backfills, analytics), not thousands of small syncs every few minutes.

## Records and metadata

**What is `FeedbackRecord`?**
The uniform internal record the assignment asks for, stored in `feedback_records`. Same columns for every
source (text, title, author, language, rating, kind, created/updated times, tenant, source, external id,
deleted_at, connector_version) plus `metadata` JSON for source-specific extras. `raw_events` = what arrived
(log and queue); `feedback_records` = what we understood (queryable, rebuildable by replay). One raw event
can become 0, 1 or many records (Intercom ping = 0, review = 1, custom batch of 3 = 3).

**How is per-source metadata typed?**
One Pydantic model per source, combined in a union picked by the `source_type` field (each model has
`source_type: Literal["playstore"]` etc.). Pydantic validates only the matching model; the record also
checks its own `source_type` equals the metadata's, so Play Store metadata cannot sit on a tweet; reading
back rebuilds the right class from JSON. New source = one new model in the union. Cost: filtering inside
JSON (`app_version = 4.2.1`) is slower than a real column; fix by indexing or promoting the few fields
people filter on (their help center describes starring a couple of key metadata fields per source).

**How would we filter or search by metadata?**
Today `GET /v1/records` filters only by source, kind and time. Ladder, cheapest first: (1) query the JSON
(`metadata->>'app_version'`), scans rows; (2) index a JSON field (Postgres expression or GIN index);
(3) promote a hot field to a real indexed column (e.g. a generated column from the JSON), chosen per
source, like Enterpret's "starred" fields; (4) a search index (Solr, Elasticsearch, OpenSearch) for
full-text, any-field filters and facets; (5) an analytics store (ClickHouse) for counts and trends.
For 4 and 5 the database stays the source of truth: feed the copy after each upsert (outbox table or the
database change log), accept a small lag, and rebuild it from `feedback_records` (itself rebuildable from
`raw_events`). Same pattern as a Solr index over the DB at Eightfold. Their public job posts name
ElasticSearch and ClickHouse. Say: "Metadata is JSON so new sources need no schema change; hot filters
get promoted to indexed columns; search goes to an index fed from the record table, always rebuildable."

**What does every connector do?**
Five things: an input model that validates the payload (bad payload: dead); `external_id` (the item's own
id); `external_event_id` (id plus version, the dedupe key); `transform` mapping into `new_record(...)` with
common fields and the metadata model; edge cases returning 0 records or raising a permanent error. Only
field names differ between sources.

**How does the custom (batch) connector differ?**
Enterpret's public webhook shape: `{"records": [...]}`. Each entry becomes its own record and its `kind`
comes from its record type (REVIEW, CONVERSATION, FORUM_CONVERSATION_THREAD, SURVEY); other connectors
take `kind` from `KIND_BY_SOURCE`. Dedupe is per batch (raw event key = hash of the whole body, the batch
is one delivery), upsert is per record (by each entry's `id`). One bad entry sends the whole batch to dead
(marked shortcut; upgrade: save the good ones, dead-letter only the bad one). Unknown type = permanent error.

**Why does a record have `external_id` but not `external_event_id`? Can we trace a record to its delivery?**
The record keeps identity and version separately: `external_id` is the key (one row per item), the version
is a comparable timestamp (`source_updated_at`, else `source_created_at`) used by `merge()`.
`external_event_id` answers "have we received this delivery?", so it lives on the raw event. Gap: a record
does not point back to the raw event that last produced it. Workaround: for most sources the raw key starts
with the item id, so search by source and key prefix (fails for custom batches, keyed by body hash).
Add-on: a `last_raw_event_id` column set in `_apply` (latest delivery only; full history needs a separate
history table).

**Why does a record copy `tenant_id` and `source_type` when a join on `source_id` would give them?**
Deliberate duplication. `tenant_id`: every read filters by tenant, so the hot path needs no join; a
composite foreign key `(source_id, tenant_id)` stops it drifting; it travels into search, analytics or a
future per-tenant split without the sources table. `source_type`: the label that picks and checks the
metadata model with no lookup, and "all Play Store reviews" needs no join. Cost: a few bytes; drift risk
removed by the foreign key and the validator.

**What does `_apply` do, and what if it fails halfway?**
Find the source, let its connector transform the payload (1 to 0, 1 or many records; nothing saved yet),
stamp `ingested_at`, upsert each (insert, update or skip; `ingested_at` only sticks on insert). Each record
saves on its own: if record 2 of 3 fails, record 1 is stored, the event retries, and record 1 is re-saved
harmlessly (same version).

**What are the save rules (`merge()`)?**
No stored record: inserted. Newer or equal version: updated (equal counts, so a replay after a fix
overwrites). Older: skipped. A delete, even an older one: applied (`deleted_at` set). Already deleted:
stays deleted, `deleted_at` is never cleared. Never changed by an update: `id`, `ingested_at`,
`source_created_at`; the stored version only moves forward. Why deletes win: a delete is final, so an
out-of-order old edit must not bring the item back. Say: "Newer or equal wins, older is ignored, deletes
are sticky and always apply, so arrival order cannot corrupt a record." Memory store keys by
`(source_id, external_id)` like the database's unique key, not by `id`, so it does not depend on how ids
are made.

**What does `new_record` guard, and what is `connector_version` for?**
Connectors pass content (text, rating, ...); `new_record` sets `id`, `tenant_id`, `source_id`,
`source_type`, `external_id` and `connector_version` after it, so a connector cannot override them (a buggy
connector passing `tenant_id="other"` still gets the source's tenant). Every connector has a version stamped
on each record: after fixing a parser, bump it and replay only records built by the old version.

**How is the SQLite save made safe, and why not ON CONFLICT?**
Read the existing row, decide with `merge()`, write, all in one locked transaction (`BEGIN IMMEDIATE`), so no
other writer gets in between. On Postgres the same rule becomes one
`INSERT ... ON CONFLICT ... DO UPDATE WHERE <newer>`. Say: "SQLite's write lock makes the simple version
safe; the single-statement form is the Postgres upgrade."

## Search and analytics (downstream of records, not built)

**How would search and analytics hang off this design?**
Rule: `feedback_records` is the source of truth; search and analytics are derived copies that lag a little
and can always be rebuilt.
- Search (Solr, Elasticsearch, OpenSearch): a post-save hook in `PipelineService._apply` after
  `feedback.upsert` returns `inserted` or `updated` sends the record to the indexer. Risk: dual write (DB
  saved, index call fails, or the reverse). Fix: write an "index me" row in the same transaction (outbox)
  and let a worker push it, or read the database change log instead of hooks; plus a periodic full reindex.
- Analytics (Redshift, StarRocks, ClickHouse): every insert/update becomes a change event (CDC such as
  Debezium, or published by our code), streamed (Kinesis Firehose, Kafka) into a 1:1 mirror table in a
  column store, so heavy queries ("complaints per app version per week") never load the main database.
- At Eightfold: post-save hooks refresh Solr; Firehose keeps an entity changelog that builds 1:1 analytics
  tables in Redshift or StarRocks. Enterpret's engineering blog describes CDC into a self-managed
  ClickHouse.
Say: "Records are the truth. Search is fed after each save through an outbox so a failed index call is
not lost. Analytics gets a 1:1 mirror through change data capture. Both are rebuildable."

## The worker

**What does the worker do?**
A loop: claim a batch, process each event one by one, nap `poll_seconds` when idle. One failed round is
logged and retried; the thread does not die. `healthy` means alive AND made progress within
max(3 × poll, 10 s); a thread spinning on database errors shows unhealthy and `/health` returns 503.

**What is a claim and a lease?**
Claiming marks events `processing` with `lease_until = now + 30 s`. Other workers skip leased events. If the
worker crashes, the lease expires and another worker takes the event. Fencing: a late worker's
"mark done" is refused because the lease is no longer its own.

**Can two workers claim the same event at once?**
No. The claim is one statement that re-checks "still free?" while updating. On SQLite writes run one at a
time; on Postgres the repeated check handles it (SKIP LOCKED is the speed upgrade). Tested: 4 threads, 40
events, each claimed exactly once.

**What if processing takes longer than the lease?**
Assumed not: one event is milliseconds against 30 s. If it did, a second worker would process it too; the
save is idempotent (same key, same version) and fencing refuses the slow worker, so the cost is wasted
work, not wrong data. Lease renewal (heartbeat) is the upgrade; or raise `FI_LEASE_SECONDS`.

**What is `next_attempt_at`?**
"Not before this time." The claim only takes pending or failed events whose `next_attempt_at` is now or
earlier. A new event gets `now` (ready at once). After each failure it moves out with backoff: +2, +4, +8,
+16 s, and the 5th failure marks it dead (wait capped at `FI_BACKOFF_CAP_SECONDS`, 300). Replay sets it
back to `now` and resets attempts. Backoff avoids hammering a struggling upstream or database.

**In what order are events claimed? Is it fair across tenants?**
Up to `batch` (10) claimable events, earliest `next_attempt_at` first (oldest waiting work first).
Claimable = pending/failed and due, or processing with an expired lease. Not fair per tenant: if tenant A
dumps 10,000 events, tenant B waits behind them (noisy neighbour). Fix: round-robin claims per tenant or a
queue per tenant (their engineering blog describes per-tenant partitioning).

**How do our queue ideas map to SQS, Redis, Kafka?**
| Ours (SQLite table) | SQS | Redis | Kafka |
|---|---|---|---|
| Claim + lease | visibility timeout | XREADGROUP pending list | partition owner + offset |
| Lease expiry retries a crash | message reappears | XAUTOCLAIM stale entries | uncommitted offset re-read |
| Backoff via `next_attempt_at` | change visibility / delay | sorted set by retry time | retry topics (no per-message delay) |
| `status = dead` | dead-letter queue | separate stream | dead-letter topic |
| Lookup by id, per-tenant dead list | no | only if indexed yourself | no |

Say: "SQS is the closest swap. Kafka changes the retry model. Either way keep a small table for lookup and
replay."

**Memory queue vs SQLite queue: which to read?**
Learn behaviour from `adapters/memory/queue.py` (plain Python). Both pass the same contract tests, so the
behaviour matches. The SQLite version only adds database guarantees: the claim is one atomic
`UPDATE ... RETURNING`; `BEGIN IMMEDIATE` and the repeated check make two workers safe; a unique constraint
enforces the dedupe key; a composite foreign key refuses a row whose tenant does not own its source.

**Why two attempt-limit checks (`>=` in `_retry`, `>` in `process`)?**
They guard different paths. `_retry`'s `>=`: the 5th normal failure goes dead immediately, with the real
error. Without it the event waits another backoff (32 s, up to 300 s), shows as `failed` as if it will
retry, and dies only on the next claim. `process`'s `>` (checked before work): catches events whose
earlier attempts crashed before anything was recorded (process killed); the claim already counted those
attempts, so `> max` means "stop".

**How is a retry done? Do we re-enqueue?**
No. The row is the queue entry, so a retry is a status change: `_retry` marks it `failed` with
`next_attempt_at = now + min(2^attempts, 300 s)`, and the claim picks it up again when due. Contrast:
SQS keeps the same message but hides it longer (change its visibility timeout); Kafka cannot delay one
message, so you publish a copy to a retry topic and move on.

**When does an event retry and when does it go dead?**
Retry (`failed`): transient errors (upstream 503/timeout, database locked) and unknown exceptions (logged
with the traceback; stored error is only "<ErrorType> (see logs)"). Dead at once: validation failure
(payload missing a field), permanent errors (unsupported topic or record type, source not found). Dead
after 5 attempts: anything still failing. Say: "Bad data cannot get better, so it goes dead and waits for
a fix plus replay. Flaky failures retry with backoff. After 5 tries anything goes dead so nothing loops
forever." Unknown errors are retried on purpose (safe if transient); the upgrade is classifying more as
permanent once seen in production.

**What does "lease lost" mean?**
This worker's lease expired and another worker re-claimed the event before this one finished. Its
"mark done" is refused (fencing: status, attempts and lease must match the copy it claimed), it logs
"lease lost" and moves on. The row is not orphaned: the newer worker finishes it. Also happens if an
admin replays the event mid-work.

**Scaling and other worker questions?**
More processes (the claim is atomic); one process handles one event at a time. Thread not async because
the database calls block and one thread is simplest.

**What actually triggers a retry on a push event today?**
Only database errors. Processing is DB read, pure `transform` (no network), DB write. `transform` can only fail
permanently (dead). A DB hiccup (`OperationalError: database is locked` after SQLite's 5 s wait) is not our
`TransientError`; it lands in the catch-all `except Exception` and retries with the same backoff, error stored as
`"OperationalError (see logs)"`. `TransientError` is raised only on the pull side today (HTTP, deadline), where
`PullService` catches it and stops the sync; it never makes a failed raw event. The pipeline's `TransientError`
branch is the slot for future network steps (enrichment, a lookup at the source).

## Tenancy and storage

**Why does the pipeline use `sources.get(id, tenant_id=...)` and not `get_by_id` plus a check?**
Same result, but the tenant is part of the lookup, so the check cannot be forgotten and a wrong-tenant
source is simply "not found". House rule: every read that knows its tenant is tenant-scoped; `get_by_id`
exists only for the webhook, where the tenant is not known yet. SQLite also refuses such a row outright
(composite foreign key).

**Anything the SQLite stores do beyond the memory ones?**
Behaviour is the same (shared contract tests). Extras: webhook secrets are stored in plain text (known gap,
"secrets at rest": encrypt the column or use a secrets manager); tenant names and API-key hashes are unique
columns, so a duplicate becomes `ValueError` and then 409; tenant scoping is a `WHERE tenant_id = ...`.

## App structure (FastAPI)

**What is `AppState` / `Ctx`?**
Built once at startup, shared by every request: adapters, services, settings (one per process; `uvicorn
--workers 4` means 4 copies). Not thread-local (Flask `g` is per request); closer to Flask
`app.extensions`. Per-request values (the tenant) come through `Depends`. Safe to share because services
keep no per-request data and each database call has its own transaction.
