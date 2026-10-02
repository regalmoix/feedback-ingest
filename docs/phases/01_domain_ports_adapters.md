# Phase 1: Domain, ports, adapters

Status: implemented 2026-10-03, three review rounds, committed

Depends on ADR-001 and ADR-002. Produces no HTTP endpoints yet.

**Update after Fleet 2 (commit cbb788c) and the tailoring pass (b8f6e2b).** The code wins over this LLD. Names and shapes that changed:
- `SourceStore.list_by_mode(mode)` is now `list_enabled(mode)` (enabled sources only). `update_cursor(source_id, tenant_id, cursor)` is tenant-scoped. The port also has `get_by_id` (webhooks only), `set_enabled` and `set_config`.
- `RawEventQueue.enqueue(event)` returns `Enqueued(id, status)`, the stored row's id and status (new or existing), not a bool. `list_by_status` also takes `source_id`. `requeue` refuses only a `processing` row whose lease is still live.
- `HttpClient.get_json(url, params: Sequence[tuple[str, str]] = ())`. `HttpxClient` follows no redirects (a 3xx is a `TransformError`), ignores proxy settings in the environment, streams the body and raises `TransientError("response too large")` past `FI_HTTP_MAX_BYTES` (2,000,000). Error messages carry the status and URL, never the body.
- `FeedbackRecord.kind` is a computed field, derived from `source_type` (for `custom`, from the record's `type`), not a validated input. `SourceType` gained `custom` and `FeedbackKind` gained `survey`.
- The schema is created at startup by `wiring.sql_adapters` (`create_all`, then `assert_schema_matches`), as well as in `tests/conftest.py`.

## What this phase builds, in one paragraph

The vocabulary of the system and the two places it stores things. "Domain" is the set of Pydantic models that
every other file talks in (Tenant, Source, RawEvent, FeedbackRecord). "Ports" are small Python Protocols that
say what the system needs from the outside world (a place to keep records, a queue of raw events, an HTTP
client, a clock) without saying how. "Adapters" are the implementations: one on SQLAlchemy/SQLite for real
runs, one in memory for fast tests. Services (next phases) only ever import ports, never adapters, so swapping
SQLite for Postgres or the table-queue for a broker stays inside the adapters (Postgres: set `FI_DATABASE_URL`, add a driver,
change three queries (claim, upsert, enqueue), add migrations).

## Plain-language glossary for this phase

- Port: a Python `Protocol` listing the methods a service may call. No code inside.
- Adapter: a class that implements a port against a real thing (SQLite) or a fake thing (a dict).
- Raw event: one inbound payload exactly as the source sent it, plus bookkeeping columns. It is both our
  audit log and our work queue.
- Lease: when a worker takes a raw event it writes `lease_until = now + N seconds`. If it crashes, the lease
  expires and another worker may take the row. This is how we survive "worker dies mid-event".
- Fence: a worker finishing a row passes back the event it claimed; the finish only applies while the row is
  still `processing` with that event's `attempts` and `lease_until`. If the row has been re-claimed since (a new
  lease, even after a requeue reset `attempts`), the finish is refused and returns False. This stops a slow
  worker whose lease expired from overwriting the newer worker's result.
- Tombstone: a `deleted_at` timestamp instead of deleting the row. The record stays queryable as deleted.

## Domain (`feedback_ingest/domain/`)

`enums.py`
- `SourceType`: discourse, playstore, twitter, intercom
- `SourceMode`: push, pull
- `FeedbackKind`: review, conversation, post  (Twitter and Discourse both map to `post`; "tweet" is a source, not a kind)
- `EventStatus`: pending, processing, processed, failed, dead
- `UpsertOutcome`: inserted, updated, skipped_older

`models.py` (Pydantic v2, `model_config = ConfigDict(frozen=True)` on every model)
- `Tenant(id: str, name: str, api_key_hash: str)`
- `Source(id: str, tenant_id: str, type: SourceType, name: str, mode: SourceMode, config: Mapping[str, str], webhook_secret: SecretStr | None = None, cursor: str | None)`
  - `config` is string-to-string on purpose (base URL, app package id, ...). `cursor` is an opaque string owned by the connector (Discourse stores an ISO timestamp).
  - `webhook_secret` is a `SecretStr` so it never shows up in `repr` or `model_dump`. A push source without a non-empty secret fails validation.
- `RawEvent(id: str, tenant_id: str, source_id: str, external_event_id: str, payload: Mapping[str, Any], received_at: datetime, status: EventStatus = pending, attempts: int = 0 (>= 0), next_attempt_at: datetime, lease_until: datetime | None = None, error: str | None = None)`
  - `external_event_id` = the source's own event/post id when the connector can see one, else `utils.hashing.payload_hash(payload)`. Unique per source so a repeated webhook never creates a second row.
- `FeedbackRecord(id: str, tenant_id: str, source_id: str, source_type: SourceType, external_id: str, kind: FeedbackKind, title: str | None, text: str, author: str | None, language: str | None, rating: int | None, source_created_at: datetime, source_updated_at: datetime | None, ingested_at: datetime, deleted_at: datetime | None, connector_version: int, metadata: SourceMetadata)`
  - Unique per `(source_id, external_id)`. Tenant scoping comes from the source row, and `tenant_id` is denormalised for fast tenant-filtered reads.
  - A model validator rejects metadata whose `source_type` disagrees with the record, and a `kind` that does not match `KIND_BY_SOURCE`. `rating` is 1..5, `connector_version` is >= 1. `version_at` = `source_updated_at or source_created_at`.
  - All datetimes are naive UTC. The `NaiveUtc` annotated type (an `AfterValidator` calling `utils.time.to_naive_utc`) converts aware datetimes to naive UTC on the way in (SQLite stores no timezone; comparing mixed values is a silent bug).

`metadata.py`
- One Pydantic model per source, each with a `source_type: Literal[...]` discriminator: `DiscourseMetadata(topic_id, post_number, like_count, topic_title, url)`, `PlaystoreMetadata(app_version, device, country)`, `TwitterMetadata(country, retweets, handle)`, `IntercomMetadata(conversation_id, part_count, tags)`.
- `SourceMetadata = Annotated[DiscourseMetadata | PlaystoreMetadata | TwitterMetadata | IntercomMetadata, Field(discriminator="source_type")]`.
- Stored as JSON via `model_dump(mode="json")`; read back by validating the row into `FeedbackRecord`, which picks the model by `source_type`. Unknown extra keys are ignored on read so older rows still load after a model gains a field.

`errors.py`
- Three plain classes, each subclassing `Exception` directly: `TransformError` for permanent payload problems (goes straight to dead), `TransientError` for retryable ones, `NotFoundError` for an unknown id. None of them carry extra fields; an HTTP status, when there is one, is in the message. `UnauthorizedError` returns in Phase 3 with the API layer.

## Ports (`feedback_ingest/ports/`): Protocols only, no logic

`stores.py`
- `TenantStore`: `add(tenant) -> None`, `get_by_api_key_hash(api_key_hash) -> Tenant | None`
- `SourceStore`: `add(source) -> None`, `get(source_id, tenant_id) -> Source | None`, `list_for_tenant(tenant_id) -> list[Source]`, `list_enabled(mode) -> list[Source]` (named `list_by_mode` before Fleet 2), `update_cursor(source_id, tenant_id, cursor) -> None` (raises `NotFoundError` for an unknown id)
- `FeedbackStore`: `upsert(record) -> UpsertOutcome`, `list_for_tenant(tenant_id, *, source_id=None, kind=None, since=None, limit=100, include_deleted=False) -> list[FeedbackRecord]` (tombstoned rows are hidden unless `include_deleted=True`)

`queue.py`
- `RawEventQueue`: `enqueue(event) -> Enqueued(id, status)` (built after Fleet 2; it was a bool: False when the `(source_id, external_event_id)` already exists), `claim(now, lease_seconds, limit) -> list[RawEvent]` (raises `ValueError` when `limit` or `lease_seconds` is < 1), `mark_processed(event) -> bool`, `mark_failed(event, error, next_attempt_at) -> bool`, `mark_dead(event, error) -> bool`, `requeue(event_id, now) -> bool` (replay: status back to pending, attempts reset), `get(event_id) -> RawEvent | None`, `list_by_status(status, *, tenant_id=None, limit=100) -> list[RawEvent]`, `counts(tenant_id=None) -> dict[EventStatus, int]`
  - The `mark_*` methods are fenced: they take the claimed event and only change a row that is still `processing` with that event's `attempts` and `lease_until`, and return False otherwise (row missing, or re-claimed by another worker). `requeue` returns False for a missing row or one that is currently `processing`.

`http.py`
- `HttpClient`: `get_json(url, params: Sequence[tuple[str, str]] = ()) -> dict[str, Any]` (was `dict[str, str]`); failures surface as `TransientError` (retry later) or `TransformError` (do not retry). The adapter below decides which.

`clock.py`
- `Clock`: `now() -> datetime` (naive UTC).

## Adapters

`adapters/sqlalchemy/db.py`: `make_engine(database_url)`; for SQLite URLs it attaches a connect listener that sets `isolation_level = None` (so SQLAlchemy emits `BEGIN` itself, the pysqlite recipe) and runs `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000` and `PRAGMA foreign_keys=ON`, plus a `begin` listener that issues `BEGIN IMMEDIATE` so every write transaction takes the write lock up front instead of failing on upgrade, and plain `BEGIN` when the connection carries the `read_only` execution option, so reads never wait on a writer. Sync engine only (no aiosqlite). There is no session helper and no schema helper: each adapter holds two sessionmakers, `self._write = sessionmaker(engine, expire_on_commit=False)` and `self._read = sessionmaker(engine.execution_options(read_only=True), expire_on_commit=False)`, and wraps each method in `with self._write.begin()` or, for every get/list/counts method, `with self._read.begin()`, and the schema is created with `Base.metadata.create_all(engine)` (in `tests/conftest.py`, and at startup in `wiring.py`). Fleet 2 moved the two sessionmakers into a `sessions(engine)` helper in `db.py`.

`adapters/sqlalchemy/tables.py`: SQLAlchemy 2.0 `Mapped[...]` declarative tables: tenants, sources, raw_events, feedback_records. Constraints: `UNIQUE(tenants.api_key_hash)`, `UNIQUE(raw_events.source_id, external_event_id)`, `UNIQUE(feedback_records.source_id, external_id)`, index on `raw_events(status, next_attempt_at)`, index on `feedback_records(tenant_id, source_created_at)`. Foreign keys: `sources.tenant_id → tenants.id` and `(source_id, tenant_id) → sources(id, tenant_id)` on both raw_events and feedback_records (backed by `UNIQUE(sources.id, tenant_id)`), so a row cannot claim a tenant other than its source's. The JSON column is named `metadata` in the DB but the attribute is `source_metadata` (SQLAlchemy reserves `.metadata`).

`adapters/sqlalchemy/stores.py`: `SqlTenantStore`, `SqlSourceStore`, `SqlFeedbackStore`. `SqlSourceStore.add` unwraps the `SecretStr` and stores the secret as plain text in the `sources` row. Upsert is read-then-write inside one transaction: load existing by `(source_id, external_id)`; insert if absent; update when the new `version_at` (`source_updated_at or source_created_at`) is >= the stored one; else return `skipped_older`, with one exception, the tombstone rule: a delete applies regardless of version, so an older record carrying `deleted_at` onto a live row sets only `deleted_at` (text and other fields stay) and returns `updated`. An update keeps the stored `id`, `source_created_at` and `ingested_at`, and a tombstone is sticky: `deleted_at` stays set even when a newer edit arrives. The version rule: every accepted update stores `source_updated_at = version_at`, so a record without `source_updated_at` still advances the stored version and a later copy with an older `source_created_at` is skipped. `# ponytail: read-then-write under BEGIN IMMEDIATE serialises all writers; switch to INSERT…ON CONFLICT when Postgres needs concurrent writers`.

`adapters/sqlalchemy/raw_event_queue.py`: `SqlRawEventQueue`. `claim` first rejects `limit` or `lease_seconds` < 1 with `ValueError`, then is ONE statement so two workers cannot take the same row. The claimable predicate is repeated on the outer UPDATE, so a row another worker grabbed between the subquery and the update is skipped, and `failed` rows whose retry time has come are claimable too:
```sql
UPDATE raw_events SET status='processing', lease_until=:lease, attempts=attempts+1
WHERE id IN (SELECT id FROM raw_events
             WHERE (status IN ('pending','failed') AND next_attempt_at <= :now)
                OR (status='processing' AND lease_until < :now)
             ORDER BY next_attempt_at LIMIT :limit)
  AND ((status IN ('pending','failed') AND next_attempt_at <= :now)
       OR (status='processing' AND lease_until < :now))
RETURNING *
```
`RETURNING` has no guaranteed order, so the claimed rows are sorted by `next_attempt_at` in Python. The `mark_*` methods are one fenced `UPDATE … WHERE id=:id AND status='processing' AND attempts=:attempts AND lease_until=:lease_until RETURNING id` that also clears `lease_until`; `requeue` is `UPDATE … WHERE id=:id AND status != 'processing'`. `# ponytail: claimable predicate repeated on the outer UPDATE keeps it race-safe on SQLite and Postgres READ COMMITTED; add FOR UPDATE SKIP LOCKED on Postgres for many workers`.

`adapters/memory/`: `MemoryTenantStore`, `MemorySourceStore`, `MemoryFeedbackStore`, `MemoryRawEventQueue`, `FixedClock(now)` (always returns the same time). Dict-backed, same semantics (including the lease-expiry rule, the fencing rule, the tombstone rule and the uniqueness rules; duplicates raise `ValueError` where SQLite raises `IntegrityError`). The one gap is foreign keys: `# ponytail: no FK check in the fake; the SQLite contract test covers tenant mismatch`.

`adapters/http/httpx_client.py`: as first built (Fleet 2 changed it, see the note at the top), `HttpxClient` wrapping `httpx.Client(timeout=10, follow_redirects=True)`, with an optional `transport` so tests can pass `httpx.MockTransport`. Any status >= 300 is an error: 408/429/5xx → `TransientError`, every other status (3xx left after redirects, other 4xx) → `TransformError`. `httpx.InvalidURL` → `TransformError`; any other `httpx.RequestError` (network, timeout, too many redirects) → `TransientError`. A body where `.json()` raises `ValueError` or `RecursionError` → `TransientError`; JSON that is not an object → `TransformError`. Status errors put the status, the URL and the first 200 characters of the body in the message.

`utils/`: `hashing.payload_hash(payload) -> str` (sha256 of `json.dumps(sort_keys=True, separators=(",",":"))`), `time.to_naive_utc(value)` and `SystemClock`, `signing.sign(secret, body) / verify(secret, body, signature)` (stdlib hmac, constant-time compare; an empty secret or signature never verifies). There is no id helper; tests build ids with `uuid4().hex`.

## Files
```
feedback_ingest/domain/{enums,models,metadata,errors}.py
feedback_ingest/ports/{stores,queue,http,clock}.py
feedback_ingest/adapters/sqlalchemy/{db,tables,stores,raw_event_queue}.py
feedback_ingest/adapters/memory/{stores,queue,clock}.py
feedback_ingest/adapters/http/httpx_client.py
feedback_ingest/utils/{hashing,time,signing}.py
tests/unit/test_models.py  tests/unit/test_utils.py  tests/unit/test_smoke.py
tests/adapters/contract.py (shared: Adapters dataclass, sample tenants/sources, record/event builders)
tests/adapters/contract_stores.py  tests/adapters/contract_upsert.py
tests/adapters/contract_queue.py  tests/adapters/contract_queue_fencing.py
tests/adapters/test_memory.py  tests/adapters/test_sqlalchemy.py  tests/adapters/test_httpx_client.py
tests/conftest.py (fixtures: tmp sqlite file engine with the schema created, fixed clock)
```
Each file ≤120 lines; split if larger.

## Tests (the success criteria)
Contract cases are written once as plain functions taking the adapter set, grouped into four lists
(`STORE_CASES` in `contract_stores.py`, `UPSERT_CASES` in `contract_upsert.py`, `QUEUE_CASES` in
`contract_queue.py`, `FENCING_CASES` in `contract_queue_fencing.py`), then run by `test_memory.py` and
`test_sqlalchemy.py` so both implementations must pass the same cases:
1. upsert same record twice → one row, second outcome `updated` (or `skipped_older` if older) and never two rows; the update keeps the stored `id`, `source_created_at` and `ingested_at`
2. upsert with older `source_updated_at` → `skipped_older`, stored text unchanged
3. upsert with `source_updated_at=None` on both sides → falls back to `source_created_at` comparison, does not silently skip; the version advances, so after a newer copy is stored an in-between copy is `skipped_older`
4. same `external_id` under two different sources of the same tenant → two rows (multi-source same type)
5. `list_for_tenant` for tenant B never returns tenant A's rows; `get(source_id, wrong_tenant)` is None
6. enqueue duplicate `(source_id, external_event_id)` → False, one row
7. claim returns pending rows whose `next_attempt_at <= now`, marks them processing with a lease, second claim returns nothing; `limit` caps each claim
8. after the lease expires (claim called with a later `now`) claim returns the row again with `attempts` incremented and a fresh lease
9. mark_failed sets `next_attempt_at` in the future and claim skips it until then; mark_dead rows are never claimed; requeue makes a dead row claimable
10. counts groups by status and respects tenant filter
11. a tombstone survives a newer edit: the row is hidden from `list_for_tenant` but returned, edited and still deleted, with `include_deleted=True`; a tombstone older than the stored version still deletes and keeps the newer text
12. filters (`source_id`, `kind`, `since`, `limit`), api-key lookup, `list_enabled` and `update_cursor` behave; duplicate tenants/sources raise, `update_cursor` on an unknown id raises `NotFoundError`
13. fencing: a worker whose lease expired and whose row was re-claimed cannot mark it dead or failed, even after a requeue reset `attempts`; `mark_*` and `requeue` on a missing id return False; `requeue` of a processing row returns False
14. aware datetimes passed to `claim`, `mark_failed` and `requeue` are normalised to naive UTC
15. `claim` with `limit` or `lease_seconds` < 1 raises `ValueError`

SQLite-only tests in `test_sqlalchemy.py`: WAL is on; a feedback record or raw event whose `tenant_id` differs
from its source's tenant is rejected with `IntegrityError`; reads (`counts`, `list_for_tenant`) do not wait while another connection holds `BEGIN IMMEDIATE`; four threads, each with its own engine, drain 40
events with `claim(limit=3)` at the same moment and every event is claimed exactly once.

`test_httpx_client.py` (httpx `MockTransport`; as first built, Fleet 2 replaced the redirect cases with "redirects are not followed", proxies ignored and the size cap): params are sent and redirects followed; 408/429/500/503 →
`TransientError` with the status and body in the message; 304, 404, a JSON array and an invalid URL → `TransformError`;
a non-JSON body and too-deeply nested JSON → `TransientError`; `ConnectError` and `TooManyRedirects` → `TransientError`.

Unit tests: naive-UTC validator, metadata discriminated union round-trip through JSON, every `SourceType` has a
metadata model, unknown metadata keys are ignored and an unknown `source_type` is rejected, a record with
mismatched `source_type`/`kind` or an out-of-range `rating`/`connector_version` is rejected, `attempts` cannot be
negative, a push source needs a non-empty secret and the secret is hidden from `repr` and dumps,
`payload_hash` is order-independent, HMAC verify rejects a tampered body, a wrong secret, an empty secret and empty or
malformed signatures.

## How to explain this phase in the interview
"Every outside dependency sits behind a small interface. The interface has two implementations, a real one and
an in-memory one, and the same contract cases run against both. That is how I know the fake behaves like the real
thing, and it is how a Postgres or broker swap stays inside the adapters. The raw-events table is the queue: a
worker takes a row by writing a lease in a single atomic UPDATE, so two workers can't take the same row, and a
crashed worker's row becomes available again when its lease expires."
