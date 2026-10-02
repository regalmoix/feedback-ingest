# Glossary

Plain words for every term you may need at the whiteboard. Each term has three lines:

- **What:** the meaning, in one sentence.
- **Where:** where it lives in this repo.
- **Why:** why it matters here.

Everything below is built: Phases 1 to 5 are merged to `main`. The one piece not built yet, replay by source and time window, says so. Paths are under `feedback_ingest/` unless they start with `tests/` or `docs/`.

The terms are in teaching order, so each one only uses words defined above it.

## 1. The big pieces

### Source type vs source instance
- **What:** A source type is a kind of service, like Playstore; a source instance is one tenant's configured connection to it, like one particular Android app.
- **Where:** Types are the `SourceType` enum in `domain/enums.py`; instances are rows in the `sources` table, the `Source` model in `domain/models.py`.
- **Why:** One tenant can have two Playstore apps, which are two `sources` rows sharing one connector, and every key uses the instance id (`source_id`), so they never collide.

### Multi-tenancy
- **What:** Many customers (tenants) share one service and one database, and each one sees only its own data.
- **Where:** A `tenant_id` column on `sources`, `raw_events` and `feedback_records` (`adapters/sqlalchemy/tables.py`), and store methods take the tenant, like `SourceStore.get(source_id, tenant_id)` in `ports/stores.py`.
- **Why:** The tests check that tenant B never sees tenant A's rows, and a source or event owned by another tenant looks exactly like a missing one, a 404 (`tenant_source` in `api/deps.py`, `_tenant_event` in `api/admin.py`).

### Connector
- **What:** The code for one source type: it checks a payload, works out its ids, turns it into feedback records, and for Discourse also fetches pages.
- **Where:** One file per source in `connectors/` (`discourse.py`, `playstore.py`, `twitter.py`, `intercom.py`, plus `discourse_pull.py` for paging), all listed in `connectors/registry.py`: `CONNECTORS` maps every type to its connector, and `PULLERS` holds the ones that can pull.
- **Why:** It is the extensibility story: adding Zendesk is one file, one metadata model, one registry entry and one fixture, with no route, worker or table changes.

### Connector version
- **What:** A whole number on each connector, bumped whenever its transform output changes, and stamped on every record it builds.
- **Where:** The `version` attribute on each connector (1 for all four today), copied into the `connector_version` column on `feedback_records`, which must be at least 1.
- **Why:** After a transform bug, you can find and replay only the rows the buggy version made.

### Port
- **What:** A small interface that lists the methods the core code may call on the outside world, with no logic inside.
- **Where:** `ports/`: `TenantStore`, `SourceStore`, `FeedbackStore` in `stores.py`, `RawEventQueue` in `queue.py`, `HttpClient` in `http.py`, `Clock` in `clock.py`.
- **Why:** The services in `services/` import ports, never adapters, so swapping SQLite for Postgres touches only the adapter files and `wiring.py`, which builds them.

### Adapter
- **What:** A class that does the real work behind a port, against a real thing or a fake one.
- **Where:** `adapters/sqlalchemy/` (SQLite, or Postgres by URL), `adapters/memory/` (dict-backed fakes plus `FixedClock`), and `adapters/http/httpx_client.py`.
- **Why:** Each store and queue port has a real adapter and an in-memory one, and that second one is how a port earns its place.

### Protocol (typing)
- **What:** A Python type, `typing.Protocol`, that lists methods; any class with those methods fits it, and nothing is inherited.
- **Where:** Every file in `ports/`, and `SourceConnector` and `PullConnector` in `connectors/base.py`.
- **Why:** mypy checks each connector against the Protocol at the registry line, so a missing method is a type error, and no base class hides the control flow.

### Contract test
- **What:** One set of test cases that every implementation must pass, which proves they behave the same.
- **Where:** The `contract_*.py` files in `tests/adapters/`, run against both the memory and the SQLite adapters, and the connector contract test in `tests/unit/connectors/`, which runs every connector over every fixture.
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
- **Where:** `utils/signing.py` has `sign` and `verify` (HMAC-SHA256, hex), with a constant-time compare, and an empty secret never verifies; `default_verify_signature` in `connectors/base.py` reads the `X-Signature` header, and the webhook route in `api/ingest.py` runs the check.
- **Why:** It runs on the raw bytes before anything is stored, so a bad signature gets a 401 and never reaches `raw_events`; the secret belongs to the source row and the algorithm belongs to the connector.

### API key hash
- **What:** We never store a tenant's API key, only a hash of it (a one-way fingerprint), and we find the tenant by that hash.
- **Where:** `Tenant.api_key_hash`, `UNIQUE(tenants.api_key_hash)` in `adapters/sqlalchemy/tables.py`, and `TenantStore.get_by_api_key_hash`; `current_tenant` in `api/deps.py` reads the `X-API-Key` header.
- **Why:** The key tells us the tenant, and no match means 401; real third-party senders cannot add our header, so for them the unguessable `source_id` in the URL plus the signature do that job.

### 202 Accepted
- **What:** The HTTP reply that means "saved, not finished yet".
- **Where:** `POST /v1/sources/{source_id}/events` in `api/ingest.py`, which replies with `raw_event_id` and `duplicate` (`raw_event_id` is null on a duplicate).
- **Why:** We send it only after the raw row is committed, and we send it for a duplicate too, so the sender stops retrying.

### 503 on DB down
- **What:** "Service unavailable": our reply when we cannot save the payload.
- **Where:** `api/errors.py` turns SQLAlchemy `OperationalError`, `InterfaceError` and `TimeoutError` into 503 `storage unavailable` on every route, the webhook included.
- **Why:** We never say yes to something we have not saved, so the sender retries and nothing is lost.

### Cursor
- **What:** A bookmark string that says where the next poll should start.
- **Where:** `Source.cursor` in the `sources` table, changed by `SourceStore.update_cursor`; Discourse stores a timestamp there, and `PullService._advance` in `services/pull.py` moves it, never backwards.
- **Why:** It moves forward only after that page's raw rows are committed, so a crash makes us fetch a page again instead of skipping it.

### Overlap window
- **What:** We set the cursor a little earlier than the newest item seen, so the next poll re-reads a few items on purpose.
- **Where:** `_OVERLAP` (60 seconds) in `connectors/discourse_pull.py`: on the final page of a run, the cursor is the newest post time seen minus that overlap.
- **Why:** It covers clock skew and late arrivals, and the repeats hit the `raw_events` unique key and are dropped.

## 3. Processing

### Lease
- **What:** When a worker takes a raw event it writes `lease_until = now + N seconds`, and if the worker dies, the lease runs out and another worker may take the row.
- **Where:** The `lease_until` column, set by `claim` in `adapters/sqlalchemy/raw_event_queue.py`, which is one single `UPDATE` statement.
- **Why:** It answers "the worker died mid-event": the row is picked up again, and the upsert makes the second run safe.

### Fence
- **What:** A worker finishing a row passes back the event it claimed, and the finish only applies if the row is still `processing` with that same `attempts` and `lease_until`.
- **Where:** `mark_processed`, `mark_failed` and `mark_dead` in both queue adapters, which return False when refused; `_finish` in `services/pipeline.py` then logs `lease lost`.
- **Why:** A slow worker whose lease ran out cannot overwrite the result of the worker that took the row after it.

### Backoff
- **What:** After a failure that might clear up, wait longer before each new try.
- **Where:** `_retry` in `services/pipeline.py` waits `2**attempts` seconds, capped by `FI_BACKOFF_CAP_SECONDS` (300), and stores the next try time with `mark_failed`; once `attempts` reaches `FI_MAX_ATTEMPTS` (5), the event goes dead instead.
- **Why:** A timeout, a 429 or a locked database often fixes itself, and backoff stops us hammering a source that is struggling.

### Dead letter
- **What:** A raw event that failed for a reason retrying cannot fix, parked with status `dead` and its error message.
- **Where:** `EventStatus.DEAD` and `mark_dead`; `services/pipeline.py` sends validation and transform errors there on the first try, and also exhausted retries and `attempt limit exceeded`; `GET /admin/raw-events?status=dead` in `api/admin.py` lists them, newest first.
- **Why:** A poison payload stops being retried but is never thrown away, so it can be fixed and replayed.

### Replay
- **What:** Running stored raw payloads through the transform again, usually after fixing a bug.
- **Where:** `requeue(event_id, now)` puts a row back to pending and resets attempts; `POST /admin/raw-events/{id}/replay` in `api/admin.py` does that for one event, and answers 409 while it is processing. Replay by source and time window is not built yet (planned, Phase 6), so today you loop over the list with `jq`.
- **Why:** Raw is kept, so a bug never means lost data; replay runs the same upsert, where an equal timestamp counts as newer (ADR-002), so a fixed row is still written, and the upsert never clears `deleted_at`, so deleted items stay deleted.

### uvicorn workers
- **What:** `uvicorn --workers N` starts N copies of the app, and each copy starts its own in-process worker.
- **Where:** The app lifespan in `main.py` starts the worker and the scheduler, using the adapters that `sql_adapters` in `wiring.py` builds; the safety comes from the single-statement claim in `adapters/sqlalchemy/raw_event_queue.py`.
- **Why:** Two workers will happen by accident, and the claim keeps it safe: a test runs four threads on 40 events and each event is claimed exactly once.

## 4. Storing records

### Upsert
- **What:** Insert a row, or update it if it already exists.
- **Where:** `upsert` in `adapters/sqlalchemy/feedback_store.py`, which returns `inserted`, `updated` or `skipped_older`.
- **Why:** An update only wins if the incoming "last changed" time (update time, or create time if missing) is newer or equal; the code today reads then writes inside one `BEGIN IMMEDIATE` transaction, and its `ponytail:` note says to switch to `INSERT ... ON CONFLICT` when Postgres needs many writers.

### Idempotency vs de-duplication
- **What:** Idempotency means doing the same thing twice leaves the same result as doing it once; de-duplication is one way to get there, by dropping the second copy.
- **Where:** Two unique keys: `raw_events (source_id, external_event_id)` drops a repeated delivery, and `feedback_records (source_id, external_id)` keeps one row per item.
- **Why:** Webhooks retry and polls overlap, so repeats are normal; the same item twice gives one row, but the same complaint on Twitter and on Discourse stays two records, because cross-source matching is out of scope.

### Tombstone
- **What:** A `deleted_at` time set on a row instead of removing the row.
- **Where:** The `deleted_at` column on `feedback_records`; the upsert in `adapters/sqlalchemy/feedback_store.py` applies a delete whatever its version and never clears it.
- **Why:** Reads hide tombstoned rows by default, and a newer edit or a replay cannot bring a deleted item back.

### Full-snapshot rule
- **What:** Every write must be the full current state of the item, never just the part that changed.
- **Where:** A rule in ADR-002 that every connector follows; Intercom webhooks already send the whole conversation, so no merge step exists.
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
