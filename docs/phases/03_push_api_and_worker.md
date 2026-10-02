# Phase 3 — Push API, pipeline, worker

Status: implemented 2026-10-03 (commit e245efe, merged ee1ec69), review fixes applied. Depends on Phases 1–2, ADR-001 and ADR-003. First phase with a runnable server.

## What this phase builds, in one paragraph

The front door and the engine. A webhook endpoint accepts a payload for one configured source, checks the
caller's API key and the source's signature, writes the payload to `raw_events` and answers 202 ("saved, not
yet processed"). A worker thread repeatedly claims a batch of raw events, runs the connector's transform, upserts
the records, and marks each event processed, failed-with-retry, or dead. Admin endpoints list dead events and
replay one. A health endpoint shows the worker is alive and how deep the queue is. The one sentence that
answers every what-if: **we save the raw payload to disk before we say yes; everything after that is a retry
or a replay.**

## Glossary
- 202 Accepted: "stored durably, will be processed". Not "processed".
- Backoff: wait longer after each failure (2, 4, 8… seconds, capped).
- Dead letter: an event we stopped retrying; it waits for a human (or a fix + replay).
- Replay: put a dead event back in the queue, usually after fixing a connector bug.

## Settings (`feedback_ingest/config.py`, pydantic-settings, env prefix `FI_`)
`database_url = "sqlite:///./feedback.db"`, `worker_enabled = True`, `worker_poll_seconds = 1.0`,
`lease_seconds = 30`, `claim_batch = 10`, `max_attempts = 5`, `backoff_cap_seconds = 300`,
`pull_interval_seconds = 300` (used in Phase 4). The five worker settings are `PositiveFloat`/`PositiveInt`,
so `FI_LEASE_SECONDS=0` fails at startup instead of at the first claim.

## App wiring (`feedback_ingest/main.py`)
- `create_app(settings: Settings | None = None) -> FastAPI`. Lifespan: `make_engine`, `Base.metadata.create_all`,
  build the four SQL adapters + `SystemClock` + `HttpxClient`, build services, start the worker thread if
  `worker_enabled`, stop it on shutdown. Everything hangs off one `AppState` Pydantic-free dataclass stored on
  `app.state.ctx` so tests can build the app with memory adapters: `create_app(settings, adapters=…)` takes an
  optional `Adapters` dataclass (tenants, sources, feedback, queue, http, clock) to override the SQL ones.
- `app = create_app()` at module bottom for `uvicorn feedback_ingest.main:app`.
- Exception handlers (`api/errors.py`): `NotFoundError → 404`, `UnauthorizedError → 401`,
  `sqlalchemy.exc.{OperationalError,InterfaceError,TimeoutError} → 503 {"detail": "storage unavailable"}`
  (DB down ⇒ never 202), logged at ERROR with method, path and traceback.
  Re-add `UnauthorizedError` to `domain/errors.py` in this phase.

## Services (all sync, constructed with ports only)
`services/ingestion.py` — `IngestionService(queue: RawEventQueue, clock: Clock)`
- `accept(source: Source, payload: Mapping[str, Any]) -> AcceptResult(raw_event_id: str, duplicate: bool)`:
  builds `RawEvent(id=uuid4().hex, tenant_id=source.tenant_id, source_id=source.id,
  external_event_id=CONNECTORS[source.type].external_event_id(payload), payload, received_at=now,
  next_attempt_at=now)` and `enqueue`s it. Used by the push endpoint now and by `PullService` in Phase 4, so
  push and pull share one path.

`services/pipeline.py` — `PipelineService(sources: SourceStore, feedback: FeedbackStore, queue: RawEventQueue, clock: Clock, max_attempts: int, backoff_cap_seconds: int)`
- `process(event: RawEvent) -> EventStatus` (the status it ended in):
  1. `source = sources.get(event.source_id, tenant_id=event.tenant_id)`; missing → `mark_dead` ("source not found").
  2. `records = CONNECTORS[source.type].transform(source, dict(event.payload))`.
  3. For each record: `record.model_copy(update={"ingested_at": now})` then `feedback.upsert(record)`.
  4. `mark_processed(event)` (fenced on the claimed event's `attempts` and `lease_until`; a False return means a newer claim owns the row, which is logged and ignored).
  - `except (ValidationError, TransformError)` → `mark_dead(event, str(exc)[:500])`.
  - `except Exception` (TransientError, OperationalError, anything unexpected) → if `event.attempts >= max_attempts`
    → dead, else `mark_failed(event, error, next_attempt_at = now + min(2**attempts, cap))`.
    Unexpected exceptions are logged at ERROR with the traceback; known transient ones at WARNING.
    Storage errors (`OperationalError`) stay on the ERROR branch on purpose: they are rarer than
    `TransientError` and worth a traceback, and services do not import sqlalchemy.
  - Any `mark_*` returning False means a newer claim owns the row: log `lease lost` at WARNING, skip the
    "processed" line, return `PROCESSING`.
  - `ValidationError` text is summarised as `loc: msg` pairs without input values, so customer text never
    reaches the log or the `error` column (the engine also uses `hide_parameters=True`).
  - All log lines carry `raw_event_id`, `tenant_id`, `source_id`, `attempts` as structured `extra=`.
  - `# ponytail: retries unknown exceptions too; classify more exceptions as permanent once we see them in prod`.

`services/worker.py` — `WorkerService(queue: RawEventQueue, pipeline: PipelineService, clock: Clock, poll_seconds: float, lease_seconds: int, batch: int)`
- `run_once() -> int`: `events = queue.claim(clock.now(), lease_seconds, batch)`; `process` each (a crash in
  one is logged as `process crashed` and the rest of the batch still runs); records `last_ok_at`; return count.
- `healthy` = alive and `clock.now() - last_ok_at <= max(3 * poll_seconds, 10 s)`. `stop()` warns if the
  thread outlives `join(lease_seconds)`; its batch is reclaimed after the lease.
- `start()` spawns a daemon `threading.Thread` running `run_once` in a loop, sleeping `poll_seconds` when a batch
  was empty, until `stop()` sets the `threading.Event`. `alive` property = thread is alive.
- `# ponytail: one thread, one process; uvicorn --workers N would start N of these, which is safe because the claim is atomic, but set FI_WORKER_ENABLED=false on all but one if you want a single consumer`.

## API (`feedback_ingest/api/`, sync `def` endpoints so FastAPI runs them in its threadpool)
`deps.py`
- `get_ctx(request) -> AppState`.
- `current_tenant(x_api_key: str = Header(alias="X-API-Key"), ctx) -> Tenant`: `sha256(x_api_key)` →
  `tenants.get_by_api_key_hash`; missing/empty → `UnauthorizedError`. (`utils/hashing.sha256_text`.)
- `tenant_source(source_id: str, tenant, ctx) -> Source`: `sources.get(source_id, tenant_id=tenant.id)` or `NotFoundError`.

`ingest.py` — `POST /v1/sources/{source_id}/events`
1. Tenant from API key (401), source for that tenant (404). The source may be push or pull; a pull connector
   also implements `transform`, so the webhook path works for any source.
2. `body = await request.body()`? No — sync endpoint: declare `body: bytes = Body(...)` via `request.body()` in
   a sync-compatible way: make this endpoint `async def`, `await request.body()`, then run the insert with
   `await run_in_threadpool(ctx.ingestion.accept, source, payload)` so the event loop never blocks on the DB.
3. `CONNECTORS[source.type].verify_signature(source.webhook_secret.get_secret_value(), body, request.headers)` →
   False → 401. Missing secret on the source → 401 as well.
4. `payload = json.loads(body)` must be a JSON object → else 400.
5. `result = ingestion.accept(source, payload)` → `202 {"raw_event_id": …, "duplicate": bool}`.
   The handler returns the `AcceptResult` dataclass directly; `accept` logs one `accepted` INFO line with
   `raw_event_id`, `tenant_id`, `source_id`, `duplicate`.

`admin.py` (tenant-scoped by API key; "admin" means operator endpoints, not a separate auth tier)
- `GET /admin/raw-events?status=dead&limit=50` → list of `RawEventView(id, source_id, status, attempts, error, received_at, next_attempt_at)`.
- `GET /admin/raw-events/{id}` → the full raw event including payload (tenant-checked).
- `POST /admin/raw-events/{id}/replay` → `requeue(id, now)`; 404 if not this tenant's or unknown; 409 if currently processing; `200 {"status": "pending"}`.
- `GET /admin/queue` → `counts(tenant_id=tenant.id)` per status.

`health.py` — `GET /health` (no auth) → `{"status": "ok", "worker_alive": bool, "queue": counts(tenant_id=None)}`;
returns 503 with `status: "degraded"` when the worker is enabled but not `healthy` (thread dead, or no
completed pass within the window, e.g. every claim failing).

## Logging
stdlib `logging`; `main.py` configures a single stream handler with a format that prints the `extra` keys
(`%(message)s raw_event_id=%(raw_event_id)s …` via a tiny `logging.Filter` that defaults missing keys to `-`).
No third-party logging library.

## Tests
`tests/api/conftest.py`: `app_client` fixture = `create_app(Settings(worker_enabled=False), adapters=memory set
with FixedClock)` inside `TestClient(app)` as a context manager; helpers to add a tenant+source and to sign a body.
- `test_push_api.py`: 401 missing/bad API key; 404 source of another tenant; 401 bad signature; 400 non-object
  JSON; 202 with `duplicate=False` then `duplicate=True` on the same body; the raw event is pending with the
  connector's `external_event_id`.
- `test_pipeline.py` (unit, memory adapters): happy path → processed + record upserted with `ingested_at = clock`;
  malformed payload → dead on first attempt; `TransientError` from a stub connector → failed with
  `next_attempt_at = now + 2**attempts`, then dead after `max_attempts`; unknown source → dead; tombstone
  record flows through.
- `test_worker.py`: `run_once` processes a claimed batch and returns the count; `start/stop` thread lifecycle;
  a crashing `process` does not kill the loop.
- `test_admin_api.py`: list dead (tenant-scoped: tenant B sees none of A's); replay dead → pending → `run_once`
  → processed; replay of processing → 409; replay unknown → 404; `/admin/queue` counts.
- `test_health.py`: ok with worker disabled flag reported; degraded when the thread is dead.
- `tests/e2e/test_push_to_query.py` (SQLite file in tmp_path, real worker thread, `Settings(worker_poll_seconds=0.05)`):
  push a signed Playstore fixture twice → wait (bounded poll ≤5 s) → exactly one feedback record in the store.
- `tests/e2e/test_restart_resume.py`: app A with `worker_enabled=False` accepts 3 events and shuts down; app B on
  the same DB file with the worker enabled → all 3 processed within the bound.
- `tests/e2e/test_dlq_replay.py`: malformed payload → dead; `POST replay` after swapping the fixture? No: replay
  of a genuinely malformed payload goes dead again (prove replay runs); then a transient-failure stub → failed →
  dead after N → replay → processed (via the memory adapters in the api tests; e2e keeps the malformed case).
- `scripts/`: nothing yet (Phase 5).

## Files
```
feedback_ingest/{main,config}.py
feedback_ingest/api/{__init__,deps,errors,ingest,admin,health,schemas}.py
feedback_ingest/services/{ingestion,pipeline,worker}.py
feedback_ingest/utils/hashing.py (+ sha256_text)
feedback_ingest/domain/errors.py (+ UnauthorizedError)
tests/api/{conftest,test_push_api,test_admin_api,test_health}.py
tests/unit/services/{test_pipeline,test_worker,test_ingestion}.py
tests/e2e/{conftest,test_push_to_query,test_restart_resume,test_dlq_replay}.py
```

## Deviations recorded
- `httpx2` is a dev dependency: Starlette's `TestClient` needs it.
- `tests/api` and `tests/e2e` are packages (`__init__.py`) so mypy accepts more than one `conftest.py`.
- `AcceptResult.raw_event_id` is `None` on a duplicate: the queue port cannot look up the stored id.
- `Adapters` and `AppState` live in `api/deps.py`, not `main.py`.
- Services are plain dataclasses.
- Pull-mode sources are accepted on the webhook too, per ADR-003 as amended (signature still required, so a
  pull source without a secret answers 401).
- `ReplayResponse` dropped: replay returns `{"status": "pending"}` as a plain dict.

## Deferred trims (done in Phase 6)
- Done: service construction and the logging and bootstrap-token helpers are inlined into `create_app`;
  `wiring.py` keeps only `sql_adapters`, which the pull e2e test reuses.
- Done: shared helpers are in `tests/helpers.py`, shared fixtures in the root `tests/conftest.py`.
- Done: `tests/api/__init__.py`, `tests/e2e/__init__.py` and both sub-conftests are deleted.

## How to explain this phase in the interview
"The webhook does three checks and one write: whose tenant, which source, is the signature right, then insert
the raw payload and answer 202. If the database is down we answer 503 and the sender retries; we never say yes
to something we haven't saved. A worker thread claims a batch with a lease, transforms, upserts, and marks the
row. Bad payloads go dead on the first try; flaky things back off and retry; after five tries they go dead too.
Dead rows are listed per tenant and replayed with one call. Health shows whether the worker is alive and how
deep the queue is, so during a firefight I look there first."
