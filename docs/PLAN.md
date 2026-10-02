# Plan: Feedback Ingestion Service (take-home round 3)

> Progress (2026-10-03): Phase 0 and Phase 1 committed after three review rounds; ADR-001..003 accepted; Phase 2–5 designs written in `docs/phases/`.

## Context

The assignment ([docs/problem_statement.pdf](docs/problem_statement.pdf)) asks for a backend that ingests
feedback records from heterogeneous sources (Intercom, Playstore, Twitter, Discourse) via both **push**
(webhook) and **pull** (poll a source API) models, under **multi-tenancy**, transforming everything into a
**uniform internal record** that still carries **source-specific metadata**. Good-to-have: **idempotency**
(de-dupe) and **multiple sources of the same type per tenant**. Evaluation: code quality, requirements
covered, extensibility (how easy is a new source). Discourse's public `search.json` + `t/{topic}/posts.json`
are the live test source.

The deliverable is demoed in-office on a whiteboard with deep cross-questioning (design choices, what-ifs,
service-down fallbacks, firefight scenarios). The user is **not writing the code** and needs material that
hand-holds them through every decision, alternative, and failure mode in plain language.

Repo state: empty except the PDF. Not a git repo yet. Toolchain present: uv 0.8, Python 3.14, node 22
(frontend not needed; skip vite).

## Decisions taken (confirmed with user)

| Decision | Choice | Why | Why not the alternatives |
|---|---|---|---|
| Storage | SQLite file via SQLAlchemy 2.0, `DATABASE_URL` env | Zero infra for demo; swap to Postgres is a URL change; unique index = idempotency in the DB, not app code | Postgres+docker: demo friction. stdlib sqlite3: hand row-mapping, harder DB swap |
| Async processing | DB-backed inbox (`raw_events` table is both the durable log and the queue) + in-process worker thread | Durable across restarts, no broker, replayable, one process to run | Redis/arq or Kafka: extra runtime; same repository interface lets us swap later. Sync inline: weak failure story |
| Connectors | All four: Discourse (pull, live), Playstore / Twitter / Intercom (push, fixtures) | Maximises "requirements addressed"; each ~40 lines | Fewer connectors proves less |
| Idempotency | `dedupe_key = sha256(tenant_id, source_id, external_id)` with UNIQUE index; upsert last-writer-wins on `source_updated_at` | DB constraint beats app-level checks under concurrency | In-memory set / Redis set: lost on restart, second component |
| Multi-tenancy | `tenant_id` column on every table; API key per tenant (`X-API-Key`); all repo queries tenant-scoped; push URL carries source id and is checked against tenant | Simple, auditable row-level isolation | Schema-per-tenant / DB-per-tenant: overkill for demo, discussed as scale path |
| Raw retention | Every inbound payload stored verbatim in `raw_events` before any transform | Enables replay after a transformer bug, DLQ, audit | Transform-then-store loses the ability to recover |
| Uniform record | One `feedback_records` table, typed common columns + `metadata` JSON validated by per-source Pydantic model | Uniform querying across sources, typed at the edge | Table-per-source: joins for cross-source queries, schema sprawl |
| Extensibility | `SourceConnector` protocol + `CONNECTORS` registry dict; new source = one file + one registry line | Clear, demonstrable on whiteboard | Plugin entry points / dynamic import: speculative |
| Infra swappability | Ports & adapters: every external interface (DB, queue, outbound HTTP, clock) is a `Protocol` in `ports/`, with one real adapter and one in-memory fake. Services depend only on ports | Swapping SQLite→Postgres or the table-queue→Kafka/SQS touches one adapter file (plus an honest change of retry model, see ADR-001); fakes make unit tests fast and prove the port has two implementations (satisfies ponytail's "no interface with one implementation") | Services calling SQLAlchemy/httpx directly: cheap now, rewrite later |
| Web/HTTP | FastAPI + httpx (MockTransport in tests, no respx) | Standard, Pydantic-native, typed | Flask/Django: heavier or less typed |
| Migrations | `metadata.create_all` at startup | Demo scope | Alembic: mentioned as prod path, not built |
| Language detection | Field exists; filled from source if provided else `None` | Requirement is a common attribute, not a detector | langdetect/fastText: enrichment stage, discussed not built |
| Frontend | None | Backend assignment | — |

Operating model (from user):
- **Zero intervention for v0 MVP.** Execution runs autonomously end to end (`builder-skills:plow-ahead` posture): ambiguities become stated assumptions in the phase LLD, no `AskUserQuestion` until the MVP is demo-ready. The user reviews the finished repo and docs.
- **Fable 5.1** (this session): architecture thinking, per-phase LLD docs, council synthesis, final review. Used sparingly.
- **Opus 5.5 medium agents** (`Agent`, `model: "opus"`): all implementation, slide deck, bulk doc drafting if Fable limit hits.
- **Ponytail enforced.** Every implementation and fix agent prompt opens by loading `ponytail:ponytail` (full) and `andrej-karpathy-skills:karpathy-guidelines`, and ends with the ladder checklist. Deliberate shortcuts carry a `# ponytail:` comment naming the ceiling and upgrade path; `ponytail:ponytail-debt` harvests them into `docs/interview/debt_ledger.md` at the end (these become "what would you do next" answers).
- **LLM council** (`Skill: anthropic-skills:llm-council`, advisors on Opus): run on the 3 decisions marked 🏛️ below. Verdicts land in `docs/decisions/`.
- **Review loop until green.** After every phase: `pr-review-toolkit:code-reviewer`, `pr-review-toolkit:silent-failure-hunter`, `ponytail:ponytail-review`, `pr-review-toolkit:type-design-analyzer` (phases 1–2), `pr-review-toolkit:pr-test-analyzer`, all in parallel on the phase diff. An Opus fix agent applies findings; the fleet re-runs on the fix diff. Repeat until every reviewer reports no findings (cap 3 rounds; leftovers logged in the phase doc). Only then does the phase commit.
- **Feedback loop.** Each phase ends with the lint/type/test gate and, from phase 3 on, an e2e run (`tests/e2e/`, real server via TestClient lifespan + SQLite file + fake HTTP) and `scripts/demo.sh`. A failing gate re-enters the fix loop; it never advances.

## Code conventions (every agent prompt carries these verbatim)
- `mypy --strict`, no `Any` outside the raw payload boundary (`dict[str, Any]` only for inbound JSON). Pydantic v2 models for every data shape crossing a boundary (API in/out, connector output, settings, stored rows via `model_validate`).
- Services are classes (`IngestionService`, `PipelineService`, `PullService`, `WorkerService`, `SchedulerService`) constructed with their ports; no module-level state except the connector registry.
- Public API of a module is the small set of methods a caller needs; helpers are `_private`. One responsibility per file, target ≤120 lines, split when larger.
- Shared helpers live in `feedback_ingest/utils/` (`hashing.py` for dedupe key, `time.py` for a `Clock` port + `to_naive_utc`, `signing.py` for HMAC) rather than being re-implemented.
- Minimal comments: only `# ponytail:` markers and the rare "why", never "what". Readable names do the explaining.
- Tests: pytest strict, one `test_*.py` per module, fakes from `adapters/memory/` for unit tests, real SQLite for repository/e2e tests, `httpx.MockTransport` for outbound HTTP.

## Architecture (what gets drawn on the whiteboard)

```
                 push (webhook)                       pull (poll)
 Source ───► POST /v1/sources/{id}/events ──┐   Scheduler/`POST /sync` ──► Puller ──► Source API (httpx)
             (HMAC verify, tenant check)    │                                  │
                                            ▼                                  ▼
                                   IngestionService.accept(envelope)  ◄────────┘
                                            │  insert raw_events (status=pending)  → 202
                                            ▼
                                   Worker (asyncio loop, lease + retry/backoff)
                                            │  CONNECTORS[source.type].transform(raw) → FeedbackRecord
                                            ▼
                                   FeedbackRepository.upsert (UNIQUE dedupe_key)
                                            │
                                 raw_events.status = processed | failed(n) | dead (DLQ)
                                            │
                       GET /v1/records?source=&kind=&since=     POST /admin/raw-events/{id}/replay
```

### Domain model (Pydantic, `feedback_ingest/domain/models.py`)
- `Tenant(id, name, api_key_hash)`
- `Source(id, tenant_id, type: SourceType, name, mode: pull|push, config: dict, webhook_secret, cursor: dict|None)`
- `RawEvent(id, tenant_id, source_id, payload: dict, received_at, status: EventStatus, attempts, next_attempt_at, error)`
- `FeedbackRecord(id, tenant_id, source_id, source_type, external_id, dedupe_key, kind: FeedbackKind, title, text, author, language, rating, source_created_at, source_updated_at, ingested_at, metadata: dict)`
- Per-source metadata models: `DiscourseMetadata(topic_id, post_number, like_count, topic_title, url)`, `PlaystoreMetadata(app_version, device, country)`, `TwitterMetadata(country, retweets, handle)`, `IntercomMetadata(conversation_id, part_count, tags)`
- Enums: `SourceType{discourse,playstore,twitter,intercom}`, `FeedbackKind{review,conversation,post,tweet}`, `EventStatus{pending,processing,processed,failed,dead}`

### Connector protocol (`feedback_ingest/connectors/base.py`)
```python
class SourceConnector(Protocol):
    source_type: SourceType
    def transform(self, source: Source, payload: dict[str, Any]) -> FeedbackRecord: ...

class PullConnector(SourceConnector, Protocol):
    async def pull(self, source: Source, client: httpx.AsyncClient) -> tuple[list[dict[str, Any]], dict[str, Any]]: ...  # payloads, new cursor

CONNECTORS: dict[SourceType, SourceConnector] = {...}
```
Discourse pull: `search.json?q=after:{cursor} before:{now}` → ids/topic_ids → `t/{topic_id}/posts.json?post_ids[]=` → one payload per post; cursor = max `created_at` minus 1-minute overlap (duplicates absorbed by idempotency).

### Folder layout
```
pyproject.toml  README.md  .python-version  .gitignore
feedback_ingest/
  main.py               app factory, lifespan wires adapters → services, starts worker + scheduler
  config.py             Settings (pydantic-settings; DATABASE_URL, WORKER_POLL_S, PULL_INTERVAL_S, MAX_ATTEMPTS)
  api/{deps,ingest,sources,records,admin,health}.py      thin routers, Pydantic request/response models
  domain/{enums,models,metadata,errors}.py
  connectors/{base,discourse,playstore,twitter,intercom}.py
  ports/{stores,queue,http,clock}.py                     Protocols only: TenantStore, SourceStore, FeedbackStore, RawEventQueue, HttpClient, Clock
  adapters/sqlalchemy/{db,tables,stores,raw_event_queue}.py SQLite/Postgres via DATABASE_URL; durable-log queue on the raw_events table
  adapters/memory/{stores,queue,clock}.py                in-memory fakes (tests, and proof the ports swap)
  adapters/http/httpx_client.py
  services/{ingestion,pipeline,pull,worker,scheduler}.py service classes depending on ports only
  utils/{hashing,signing,time}.py
tests/
  conftest.py  fixtures/*.json
  unit/        test_models.py test_connectors.py test_pipeline.py test_pull.py test_worker.py (memory adapters)
  adapters/    test_sqlalchemy_stores.py test_raw_event_queue.py (real SQLite file, lease + unique index)
  api/         test_push_api.py test_sources_api.py test_records_api.py test_tenancy.py test_admin_api.py
  e2e/         test_push_to_query.py test_pull_to_query.py test_restart_resume.py test_dlq_replay.py
  live/        test_discourse_live.py   (marker `live`, skipped by default)
scripts/seed.py  scripts/demo.sh
docs/
  problem_statement.pdf
  PLAN.md                        this plan, copied verbatim in phase 0 and kept current
  00_architecture.md            the one-page story + mermaid diagrams
  phases/01..06_*.md             LLD per phase (written before each phase)
  decisions/ADR-001..003.md      council verdicts
  interview/whiteboard.md        what to draw, in what order, 10-minute script
  interview/qa_bank.md           question → short answer → deeper answer
  interview/failure_scenarios.md component down → symptom → what the code does → what prod would add
  interview/firefight_runbook.md "client says reviews missing since yesterday" step-by-step
  interview/alternatives.md      every rejected option and why
  interview/extensions.md        new source in 5 steps, Kafka swap, Postgres swap, scale-out
  interview/glossary.md          plain-language terms (inbox/durable log, DLQ, idempotency, cursor, HMAC, lease)
  slides/deck.pptx               built last from 00_architecture + interview docs (private, local file)
```

Tooling (`pyproject.toml`): uv project; deps `fastapi, uvicorn, sqlalchemy>=2, httpx, pydantic>=2, pydantic-settings`; dev `pytest, pytest-asyncio, mypy, ruff`. `ruff` select ALL with a short ignore list; `mypy --strict`; pytest `-W error`, `--strict-markers`, `live` marker. Commands: `uv run pytest`, `uv run mypy .`, `uv run ruff check . && uv run ruff format --check .`, `uv run uvicorn feedback_ingest.main:app`.

## Phases

Each phase = (a) Fable writes a 1-page LLD in `docs/phases/NN_*.md` in plain language (what, why, data flow, files, tests, how to explain it in the interview); (b) one Opus 5.5 medium Agent implements from the LLD with karpathy + ponytail rules; (c) reviewer fleet; (d) Opus fix agent; (e) `pytest + mypy + ruff` green; (f) git commit.

### Phase 0 — Scaffold + ADRs (no business code)
- `git init` (private, never pushed publicly), `uv init`, pyproject with strict tool config, empty package, `tests/conftest.py`, README skeleton, `docs/00_architecture.md` v1, `.gitignore`.
- Copy this plan to `docs/PLAN.md`; every later phase updates its status line there.
- 🏛️ Council #1: storage+queue shape (confirm SQLite inbox-table queue vs alternatives) → `ADR-001`.
- 🏛️ Council #2: uniform record schema + dedupe key + metadata-as-JSON → `ADR-002`.
- Verify: `uv run pytest` (0 tests, exit 0), `mypy`, `ruff` all pass on empty package.

### Phase 1 — Domain, ports, adapters
- Enums, Pydantic models, per-source metadata models, `domain/errors.py`.
- `ports/`: `TenantStore.by_api_key`, `SourceStore.get/list_pull/create/update_cursor`, `FeedbackStore.upsert/list`, `RawEventQueue.enqueue/claim(lease)/mark_processed(event)/mark_failed(event, error, next_attempt_at)/mark_dead(event, error)/requeue/list_by_status`, `HttpClient.get_json`, `Clock.now`.
- `adapters/sqlalchemy/`: tables (UNIQUE `dedupe_key`, index `(tenant_id, source_id, status, next_attempt_at)` on raw_events), engine from `DATABASE_URL`, one class per port. `adapters/memory/`: dict-backed fakes with identical behaviour.
- `utils/hashing.dedupe_key`, `utils/time` (`SystemClock`), `utils/signing` (HMAC).
- Tests: a shared contract test module runs the same cases against both the SQLite and memory adapters (upsert twice → one row; older `source_updated_at` doesn't overwrite; claim leases and skips leased; lease expiry re-claims; tenant A cannot read B).
- Reviewer fleet includes `type-design-analyzer`.

### Phase 2 — Connectors + transform
- `base.py` protocol + registry; four connectors; `tests/fixtures/{discourse_post,playstore_review,twitter_tweet,intercom_conversation}.json` (synthetic, no real user data).
- 🏛️ Council #3: connector abstraction shape (protocol+registry vs class hierarchy vs config-driven mapping) → `ADR-003`.
- Tests: each fixture → expected `FeedbackRecord` (kind, text, external_id, metadata validated by its model); malformed payload raises `TransformError`; `CONNECTORS` covers every `SourceType`.

### Phase 3 — Push API + worker pipeline
- `POST /v1/sources/{source_id}/events`: `X-API-Key` → tenant; source must belong to tenant; HMAC-SHA256 `X-Signature` check with source secret (stdlib `hmac`); insert raw → `202 {raw_event_id}`. Returns `503` if DB write fails (never ack what isn't durable).
- `services/pipeline.py`: raw → connector.transform → upsert → mark processed; on exception mark failed with backoff `2**attempts` s; after `MAX_ATTEMPTS` → `dead`.
- `services/worker.py`: asyncio loop, `claim_batch` with lease, processes, started in lifespan; `GET /health` reports worker alive + pending/dead counts.
- `POST /admin/raw-events/{id}/replay`, `GET /admin/raw-events?status=dead`.
- Tests (FastAPI TestClient): bad signature → 401; wrong tenant → 404; duplicate webhook → one record; transform failure → failed→dead after N; replay of dead → processed; worker crash simulation (lease expiry re-claim).

### Phase 4 — Pull integration (Discourse)
- `connectors/discourse.py` `pull()`; `services/puller.py` runs pull for one source, feeds payloads through `IngestionService.accept` (same path as push, so same idempotency/retry), updates cursor only after raw rows are durably inserted.
- `POST /v1/sources/{id}/sync` (manual trigger) + `services/scheduler.py` loop every `PULL_INTERVAL_S` over pull-mode sources. 429/5xx → retry with backoff, cursor untouched.
- Tests: httpx `MockTransport` for both Discourse endpoints; cursor advances; overlap window produces duplicates that dedupe; 500 → cursor unchanged; `test_discourse_live.py` hits meta.discourse.org under `-m live`.

### Phase 5 — Tenancy, query API, seed, demo
- `GET /v1/records?source_id=&kind=&since=&limit=` tenant-scoped; `GET/POST /v1/sources` (create a second Playstore source for same tenant → proves multi-source-same-type).
- `scripts/seed.py`: two tenants, each with Discourse (pull) + two Playstore (push) + Twitter + Intercom sources; prints API keys and webhook secrets.
- `scripts/demo.sh`: start server, seed, push a signed Playstore review twice (show one record), trigger Discourse sync, list records, kill-and-restart server mid-queue (show pending rows resume), replay a dead event.
- Tests: tenancy isolation end-to-end; two same-type sources yield distinct records for same external_id.

### Phase 6 — Hardening + interview pack
- stdlib `logging` with `tenant_id/source_id/raw_event_id` in every pipeline log line; counters exposed on `/health`.
- `docs/interview/*` written by Fable (short, plain), expanded by an Opus agent where bulk is needed; `docs/00_architecture.md` final with mermaid: component, push sequence, pull sequence, retry/DLQ/replay state machine.
- Slide deck via `anthropic-skills:pptx` (Opus agent) from the docs. Stays a local file; nothing published.
- README: run in 3 commands, design summary, links to all docs.
- Final full reviewer fleet + `ponytail:ponytail-audit` over whole repo.

## Interview prep coverage (what `docs/interview/` must answer)

Failure scenarios (each: symptom → what this code does → what prod adds):
source API down / 429 · DB down on push (503, source retries) · DB down on pull (skip tick) · worker crash mid-event (lease expiry, idempotent reprocess) · duplicate webhooks · out-of-order updates (`source_updated_at` guard) · transformer bug after deploy (fix + replay from raw) · poison payload (DLQ) · noisy tenant (per-tenant rate limit / queue partitioning) · secret leak (rotate per source) · schema change at source (metadata JSON + connector version) · backfill request (sync with explicit range) · clock skew in cursors (overlap window) · service restart with 10k pending (batch size + lease).

Scale/extension questions: Kafka/SQS swap (repository boundary), Postgres swap (`DATABASE_URL`), horizontal workers (lease + `SKIP LOCKED` on Postgres), partitioning by tenant, analytics store (ClickHouse), language detection + PII scrubbing as enrichment stages, deletes/tombstones, exactly-once vs at-least-once + idempotent (why we chose the latter), observability (metrics, tracing by `raw_event_id`), multi-region.

Firefight runbook: "client says Playstore reviews missing since yesterday" → check source cursor/last sync → `/admin/raw-events?status=dead` → logs by `source_id` → replay / manual sync with range → comms template.

## Verification (end to end)
1. `uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest` all green after every phase; reviewer fleet reports zero findings before each commit.
1b. `tests/e2e/` green from phase 3 on: push twice → one record queryable; pull via fake Discourse → records; stop app with pending rows → restart → processed; dead event → replay → processed.
2. `uv run pytest -m live` passes against meta.discourse.org (network) at least once before demo.
3. `scripts/demo.sh` runs clean on a fresh clone and prints: one record after duplicate push, N records after Discourse sync, resumed pending after restart, replayed dead event.
4. Walk-through: user reads `docs/interview/whiteboard.md` and can reproduce the diagram + answer the top 20 Q&A without opening code.

## Out of scope (say so if asked)
Alembic migrations, auth beyond API key, real Playstore/Twitter/Intercom API clients (fixtures only), language detection model, UI, Kafka/Redis, Docker image (optional 10-line Dockerfile if time remains).
