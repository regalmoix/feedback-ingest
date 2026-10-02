# Glossary

Plain words for every term you may need at the whiteboard. Each term has three lines:

- **What:** the meaning, in one sentence.
- **Where:** where it lives in this repo.
- **Why:** why it matters here.

**Built** means it is in the code today (Phase 1). **Planned (Phase N)** means it is designed in `docs/phases/` but not written yet. Paths are under `feedback_ingest/` unless they start with `tests/` or `docs/`.

The terms are in teaching order, so each one only uses words defined above it.

## 1. The big pieces

### Source type vs source instance
- **What:** A source type is a kind of service, like Playstore; a source instance is one tenant's configured connection to it, like one particular Android app.
- **Where:** Types are the `SourceType` enum in `domain/enums.py`; instances are rows in the `sources` table, the `Source` model in `domain/models.py`.
- **Why:** One tenant can have two Playstore apps, which are two `sources` rows sharing one connector, and every key uses the instance id (`source_id`), so they never collide.

### Multi-tenancy
- **What:** Many customers (tenants) share one service and one database, and each one sees only its own data.
- **Where:** A `tenant_id` column on `sources`, `raw_events` and `feedback_records` (`adapters/sqlalchemy/tables.py`), and store methods take the tenant, like `SourceStore.get(source_id, tenant_id)` in `ports/stores.py`.
- **Why:** The Phase 1 tests check that tenant B never sees tenant A's rows, and a source owned by another tenant will look exactly like a missing one, a 404 (planned, Phase 3).

### Connector
- **What:** The code for one source type: it checks a payload, works out its ids, turns it into feedback records, and for Discourse also fetches pages.
- **Where:** Planned (Phase 2): one file per source in `connectors/`, all listed in the `CONNECTORS` dict in `connectors/registry.py`; the folder is empty today.
- **Why:** It is the extensibility story: adding Zendesk is one file, one metadata model, one dict entry and one fixture, with no route, worker or table changes.

### Connector version
- **What:** A whole number on each connector, bumped whenever its transform output changes, and stamped on every record it builds.
- **Where:** The `connector_version` column on `feedback_records` (built, must be at least 1); the `version` attribute on each connector is planned (Phase 2).
- **Why:** After a transform bug, you can find and replay only the rows the buggy version made.

### Port
- **What:** A small interface that lists the methods the core code may call on the outside world, with no logic inside.
- **Where:** `ports/`: `TenantStore`, `SourceStore`, `FeedbackStore` in `stores.py`, `RawEventQueue` in `queue.py`, `HttpClient` in `http.py`, `Clock` in `clock.py`.
- **Why:** Services (planned, Phase 3) will import only ports, so swapping SQLite for Postgres touches one adapter file.

### Adapter
- **What:** A class that does the real work behind a port, against a real thing or a fake one.
- **Where:** `adapters/sqlalchemy/` (SQLite, or Postgres by URL), `adapters/memory/` (dict-backed fakes plus `FixedClock`), and `adapters/http/httpx_client.py`.
- **Why:** Each store and queue port has a real adapter and an in-memory one, and that second one is how a port earns its place.

### Protocol (typing)
- **What:** A Python type, `typing.Protocol`, that lists methods; any class with those methods fits it, and nothing is inherited.
- **Where:** Every file in `ports/`, and the planned (Phase 2) `SourceConnector` and `PullConnector` in `connectors/base.py`.
- **Why:** mypy checks each connector against the Protocol at the registry line, so a missing method is a type error, and no base class hides the control flow.

### Contract test
- **What:** One set of test cases that every implementation must pass, which proves they behave the same.
- **Where:** Built: `tests/adapters/contract_*.py`, run by both `tests/adapters/test_memory.py` and `tests/adapters/test_sqlalchemy.py`; planned (Phase 2): `tests/unit/connectors/test_contract.py`, which runs every connector over every fixture.
- **Why:** It is how we know the fake behaves like SQLite, and it forces a new connector to be complete before the test goes green.

## 2. Getting data in

### Raw event
- **What:** One incoming payload stored exactly as the source sent it, plus bookkeeping like status, attempts and lease time.
- **Where:** The `RawEvent` model in `domain/models.py` and the `raw_events` table, unique on `(source_id, external_event_id)`.
- **Why:** It is both the audit log and the work queue, so nothing is lost and anything can be run again.

### Inbox / durable log (and why not "outbox")
- **What:** Durable means "on disk, survives a crash"; the inbox is the table where every incoming payload lands before we reply.
- **Where:** The `raw_events` table, used through the `RawEventQueue` port (`ports/queue.py`, adapter `adapters/sqlalchemy/raw_event_queue.py`).
- **Why:** Push and pull both write here and one worker reads it; we never call it an outbox, because an outbox holds messages we will send out, and this table holds what came in.

### HMAC signature
- **What:** A short code made from the request body and a shared secret; only someone who knows the secret can make it, so it proves the sender and that the body was not changed.
- **Where:** `utils/signing.py` has `sign` and `verify`, with a constant-time compare, and an empty secret never verifies (built); the default check (HMAC-SHA256, hex, header `X-Signature`) is planned (Phase 2), and the check in the webhook router is planned (Phase 3).
- **Why:** It runs on the raw bytes before anything is stored, so a bad signature gets a 401 and never reaches `raw_events`; the secret belongs to the source row and the algorithm belongs to the connector.

### API key hash
- **What:** We never store a tenant's API key, only a hash of it (a one-way fingerprint), and we find the tenant by that hash.
- **Where:** `Tenant.api_key_hash`, `UNIQUE(tenants.api_key_hash)` in `adapters/sqlalchemy/tables.py`, and `TenantStore.get_by_api_key_hash` (built); reading the `X-API-Key` header is planned (Phase 3).
- **Why:** The key tells us the tenant, and no match means 401; real third-party senders cannot add our header, so for them the unguessable `source_id` in the URL plus the signature do that job.

### 202 Accepted
- **What:** The HTTP reply that means "saved, not finished yet".
- **Where:** Planned (Phase 3) on `POST /v1/sources/{source_id}/events`, with the `raw_event_id` in the reply.
- **Why:** We send it only after the raw row is committed, and we send it for a duplicate too, so the sender stops retrying.

### 503 on DB down
- **What:** "Service unavailable": our reply when we cannot save the payload.
- **Where:** Planned (Phase 3) in the webhook route, when the database write fails.
- **Why:** We never say yes to something we have not saved, so the sender retries and nothing is lost.

### Cursor
- **What:** A bookmark string that says where the next poll should start.
- **Where:** `Source.cursor` in the `sources` table, changed by `SourceStore.update_cursor` (built); Discourse stores a timestamp there, and the poll service that moves it is planned (Phase 4).
- **Why:** It moves forward only after that page's raw rows are committed, so a crash makes us fetch a page again instead of skipping it.

### Overlap window
- **What:** We set the cursor a little earlier than the newest item seen, so the next poll re-reads a few items on purpose.
- **Where:** Planned (Phase 4) in the Discourse connector: the cursor is the page's newest timestamp minus a small overlap (PLAN.md says one minute).
- **Why:** It covers clock skew and late arrivals, and the repeats hit the `raw_events` unique key and are dropped.

## 3. Processing

### Lease
- **What:** When a worker takes a raw event it writes `lease_until = now + N seconds`, and if the worker dies, the lease runs out and another worker may take the row.
- **Where:** The `lease_until` column, set by `claim` in `adapters/sqlalchemy/raw_event_queue.py`, which is one single `UPDATE` statement (built).
- **Why:** It answers "the worker died mid-event": the row is picked up again, and the upsert makes the second run safe.

### Fence
- **What:** A worker finishing a row passes back the event it claimed, and the finish only applies if the row is still `processing` with that same `attempts` and `lease_until`.
- **Where:** `mark_processed`, `mark_failed` and `mark_dead` in both queue adapters, which return False when refused (built, tested in `tests/adapters/contract_queue_fencing.py`).
- **Why:** A slow worker whose lease ran out cannot overwrite the result of the worker that took the row after it.

### Backoff
- **What:** After a failure that might clear up, wait longer before each new try.
- **Where:** `mark_failed(event, error, next_attempt_at)` stores the next try time (built); the worker that picks the wait, `2**attempts` seconds, and gives up after `MAX_ATTEMPTS`, is planned (Phase 3).
- **Why:** A timeout, a 429 or a locked database often fixes itself, and backoff stops us hammering a source that is struggling.

### Dead letter
- **What:** A raw event that failed for a reason retrying cannot fix, parked with status `dead` and its error message.
- **Where:** `EventStatus.dead` and `mark_dead` (built); the worker sending validation and transform errors there, and `GET /admin/raw-events?status=dead`, are planned (Phase 3).
- **Why:** A poison payload stops being retried but is never thrown away, so it can be fixed and replayed.

### Replay
- **What:** Running stored raw payloads through the transform again, usually after fixing a bug.
- **Where:** `requeue(event_id, now)` puts a row back to pending and resets attempts (built); `POST /admin/raw-events/{id}/replay` is planned (Phase 3), and filtering by source and time window is planned (Phase 6).
- **Why:** Raw is kept, so a bug never means lost data; by design (ADR-002) the replay write skips the timestamp check so a fixed row is still written, and deletes replay in order so deleted items stay deleted.

### uvicorn workers
- **What:** `uvicorn --workers N` starts N copies of the app, and each copy starts its own in-process worker.
- **Where:** The worker started with the app is planned (Phase 3); the safety comes from the single-statement claim, which is built.
- **Why:** Two workers will happen by accident, and the claim keeps it safe: a Phase 1 test runs four threads on 40 events and each event is claimed exactly once.

## 4. Storing records

### Upsert
- **What:** Insert a row, or update it if it already exists.
- **Where:** `upsert` in `adapters/sqlalchemy/stores.py`, which returns `inserted`, `updated` or `skipped_older`.
- **Why:** An update only wins if the incoming "last changed" time (update time, or create time if missing) is newer or equal; the code today reads then writes inside one `BEGIN IMMEDIATE` transaction, and its `ponytail:` note says to switch to `INSERT ... ON CONFLICT` when Postgres needs many writers.

### Idempotency vs de-duplication
- **What:** Idempotency means doing the same thing twice leaves the same result as doing it once; de-duplication is one way to get there, by dropping the second copy.
- **Where:** Two unique keys: `raw_events (source_id, external_event_id)` drops a repeated delivery, and `feedback_records (source_id, external_id)` keeps one row per item.
- **Why:** Webhooks retry and polls overlap, so repeats are normal; the same item twice gives one row, but the same complaint on Twitter and on Discourse stays two records, because cross-source matching is out of scope.

### Tombstone
- **What:** A `deleted_at` time set on a row instead of removing the row.
- **Where:** The `deleted_at` column on `feedback_records`; the upsert in `adapters/sqlalchemy/stores.py` applies a delete whatever its version and never clears it.
- **Why:** Reads hide tombstoned rows by default, and a newer edit or a replay cannot bring a deleted item back.

### Full-snapshot rule
- **What:** Every write must be the full current state of the item, never just the part that changed.
- **Where:** A rule in ADR-002 that each connector must follow (planned, Phase 2); Intercom webhooks already send the whole conversation, so no merge step exists.
- **Why:** The upsert replaces the row, so a partial payload would wipe the rest; a source that sends only changes must fetch the full object first.

### Discriminated union
- **What:** A type that can be one of several models, where one field, here `source_type`, says which one it is.
- **Where:** `SourceMetadata` in `domain/metadata.py`, over `DiscourseMetadata`, `PlaystoreMetadata`, `TwitterMetadata` and `IntercomMetadata`.
- **Why:** Pydantic and mypy always know which model a `metadata` blob is, and `FeedbackRecord` rejects metadata whose `source_type` disagrees with the record.

### Naive UTC
- **What:** A date and time in UTC with no timezone attached.
- **Where:** `to_naive_utc` in `utils/time.py`, used by the `NaiveUtc` type in `domain/models.py` to convert every incoming datetime.
- **Why:** SQLite stores datetimes as text and drops timezones, so if every value is naive UTC, text order matches time order; mixing the two kinds is a silent bug.

### Composite foreign key
- **What:** A foreign key over two columns at once.
- **Where:** `(source_id, tenant_id) -> sources(id, tenant_id)` on `raw_events` and `feedback_records`, backed by `UNIQUE(sources.id, tenant_id)` in `adapters/sqlalchemy/tables.py`, and it needs `PRAGMA foreign_keys=ON`.
- **Why:** The database itself refuses a row whose tenant differs from its source's tenant; a SQLite-only test checks this, because the memory fake has no foreign keys.

## 5. SQLite settings

### WAL
- **What:** Write-Ahead Logging, a SQLite mode where readers keep reading while one writer writes.
- **Where:** `PRAGMA journal_mode=WAL`, set on every connection by `make_engine` in `adapters/sqlalchemy/db.py`; a test checks it is on.
- **Why:** The API, the worker and health checks can read while a write is in progress.

### busy_timeout
- **What:** How long SQLite waits for a lock before failing with "database is locked".
- **Where:** `PRAGMA busy_timeout=5000`, which is 5 seconds, also in `make_engine`.
- **Why:** Under a burst, a writer waits briefly instead of failing.

### BEGIN IMMEDIATE
- **What:** Start a transaction and take the write lock right away, not at the first write.
- **Where:** A `begin` listener in `adapters/sqlalchemy/db.py`; connections marked `read_only` use a plain `BEGIN` instead.
- **Why:** A transaction that reads and then writes can fail when it tries to upgrade its lock, so taking it up front avoids that, and reads never wait on a writer (a test checks this).
