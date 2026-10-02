# Feedback Ingestion Service

A multi-tenant backend that ingests customer feedback from heterogeneous sources (Intercom, Play Store,
Twitter, Discourse) by both push (signed webhooks) and pull (polling Discourse's public API). Every payload
is saved verbatim in a `raw_events` table before the API answers 202. A background worker transforms each
one into a uniform, de-duplicated `FeedbackRecord` that keeps common fields (kind, text, author, language,
rating, tenant, source) plus typed source-specific metadata. Failures retry with backoff, then park in a
dead list that can be replayed.

## Run

```sh
uv sync
uv run pytest
uv run uvicorn feedback_ingest.main:app
```

## Demo

`scripts/demo.sh` (needs `uv`, `curl`, `jq`; uses `demo.db` and port 8000) runs the whole story:

1. Starts the server and shows `/health`.
2. Seeds two tenants (`acme`, `globex`), each with a Discourse pull source, two Play Store, one Twitter and one Intercom push source.
3. Pushes the same signed Play Store review twice: `duplicate=false`, then `duplicate=true`.
4. Pushes it to a second Play Store source of the same tenant.
5. `acme` sees two review records (same `external_id`, two sources); `globex` sees none.
6. A malformed payload goes dead; replay runs it again and it goes dead again.
7. A live Discourse sync against meta.discourse.org (2021-01-01 to 2021-01-05) and the resulting posts.
8. Twenty pushes queued with the worker off, `kill -9`, restart: the backlog drains.
9. Stops the server.

`uv run pytest -m live` runs the live Discourse test (`tests/live/test_discourse_live.py`, needs network).

## Design in ten lines

1. Two ways in, one pipe: webhooks and the Discourse poller both call `IngestionService.accept`.
2. `raw_events` is both the audit log and the work queue; the API returns 202 only after the row commits, 503 if it cannot.
3. `UNIQUE(source_id, external_event_id)` makes a repeated webhook or an overlapping poll a no-op.
4. `WorkerService` claims rows with a lease in one atomic UPDATE; a crashed worker's rows come back when the lease expires.
5. `PipelineService` runs `CONNECTORS[type].transform`, then `FeedbackStore.upsert` on `UNIQUE(source_id, external_id)`.
6. The newer source version wins, older copies are skipped, and deletes are sticky tombstones (`deleted_at`).
7. Transient errors retry at `2^attempts` seconds (capped); bad payloads and exhausted attempts go `dead`; replay resets them.
8. Tenancy: API key hash to tenant, every query takes `tenant_id`, composite FKs tie rows to their source's tenant.
9. Ports and adapters: services see Protocols only; SQLite/SQLAlchemy and httpx adapters, in-memory fakes for tests.
10. A new source is one connector file plus one registry line; the pipeline does not change.

## Settings

All read from the environment by `feedback_ingest/config.py` (prefix `FI_`).

| Setting | Default | Meaning |
|---|---|---|
| `FI_DATABASE_URL` | `sqlite:///./feedback.db` | SQLAlchemy URL |
| `FI_WORKER_ENABLED` | `true` | Start the background worker |
| `FI_WORKER_POLL_SECONDS` | `1.0` | Worker sleep when the queue is empty |
| `FI_LEASE_SECONDS` | `30` | How long a claimed row stays leased |
| `FI_CLAIM_BATCH` | `10` | Rows per claim |
| `FI_MAX_ATTEMPTS` | `5` | Attempts before a row goes dead |
| `FI_BACKOFF_CAP_SECONDS` | `300` | Ceiling on the `2^attempts` retry delay |
| `FI_PULL_INTERVAL_SECONDS` | `300` | Scheduler tick for pull sources |
| `FI_SCHEDULER_ENABLED` | `true` | Start the pull scheduler |
| `FI_BOOTSTRAP_TOKEN` | `change-me` | Guards `POST /admin/tenants`; empty disables it; startup warns on the default |

`scripts/seed.py` also reads `FI_BASE_URL` (default `http://127.0.0.1:8000`) and `FI_BOOTSTRAP_TOKEN`.

## API

| Route | Auth | Purpose |
|---|---|---|
| `GET /health` | none | Worker and scheduler liveness, queue counts; 503 when degraded |
| `POST /admin/tenants` | `X-Bootstrap-Token` | Create a tenant; returns its API key once |
| `POST /v1/sources` | `X-API-Key` | Create a source; a push source gets a webhook secret, shown once |
| `GET /v1/sources` | `X-API-Key` | List the tenant's sources, secrets masked |
| `GET /v1/sources/{id}` | `X-API-Key` | One source |
| `PATCH /v1/sources/{id}` | `X-API-Key` | Enable or disable a source |
| `POST /v1/sources/{id}/events` | `X-API-Key` + `X-Signature` | Push webhook: HMAC-SHA256 of the body, 202 with `raw_event_id` and `duplicate` |
| `POST /v1/sources/{id}/sync` | `X-API-Key` | Pull now; returns pages, accepted, duplicates, cursor, error |
| `GET /v1/records` | `X-API-Key` | Query records: `source_id`, `kind`, `since`, `limit`, `include_deleted` |
| `GET /v1/records/{id}` | `X-API-Key` | One record |
| `GET /admin/raw-events` | `X-API-Key` | Raw events by `status` (default `dead`), newest first, `limit` |
| `GET /admin/raw-events/{id}` | `X-API-Key` | One raw event with its payload and error |
| `POST /admin/raw-events/{id}/replay` | `X-API-Key` | Back to `pending` with attempts reset; 409 while processing |
| `GET /admin/queue` | `X-API-Key` | The tenant's raw-event counts per status |

A source or event id that belongs to another tenant answers 404.

## Docs

- [Plan](docs/PLAN.md)
- [Architecture](docs/00_architecture.md): diagrams, module map, requirements map
- Decisions: [ADR-001 storage and queue](docs/decisions/ADR-001-storage-and-queue.md),
  [ADR-002 record and idempotency](docs/decisions/ADR-002-uniform-record-and-idempotency.md),
  [ADR-003 connectors](docs/decisions/ADR-003-connector-abstraction.md)
- Phases: [01 domain, ports, adapters](docs/phases/01_domain_ports_adapters.md),
  [02 connectors](docs/phases/02_connectors.md), [03 push API and worker](docs/phases/03_push_api_and_worker.md),
  [04 pull](docs/phases/04_pull_integration.md), [05 tenancy, query, seed, demo](docs/phases/05_tenancy_query_seed_demo.md),
  [06 hardening and interview pack](docs/phases/06_hardening_interview_pack.md)
- Interview pack: [whiteboard](docs/interview/whiteboard.md), [failure scenarios](docs/interview/failure_scenarios.md),
  [firefight runbook](docs/interview/firefight_runbook.md), [alternatives](docs/interview/alternatives.md),
  [glossary](docs/interview/glossary.md), [Q&A bank](docs/interview/qa_bank.md) (likely questions with short answers),
  [extensions](docs/interview/extensions.md) (recipes for "how would you add X?"),
  [debt ledger](docs/interview/debt_ledger.md) (every `ponytail:` shortcut and when to fix it),
  [demo script](docs/interview/demo_script.md) (what to say at each step of `scripts/demo.sh`)

## Status of requirements

| Requirement | Level | Where | Proved by |
|---|---|---|---|
| Heterogeneous sources | Must | `connectors/` | `tests/unit/connectors/` |
| Push and pull | Must | `api/ingest.py`, `services/pull.py`, `services/scheduler.py` | `tests/e2e/test_push_to_query.py`, `tests/e2e/test_pull_to_query.py` |
| Source-specific metadata | Must | `domain/metadata.py` | `tests/unit/test_models.py` |
| Multi-tenancy | Must | `api/deps.py`, `adapters/sqlalchemy/tables.py` | `tests/adapters/contract_stores.py`, `tests/api/test_records_api.py` |
| Uniform structure, record types, common attributes | Must | `domain/models.py` | `tests/unit/connectors/test_contract.py` |
| Idempotency | Good-to-have | UNIQUE keys, `SqlFeedbackStore.upsert` | `tests/e2e/test_push_to_query.py`, `tests/adapters/contract_upsert.py` |
| Several sources of one type per tenant | Good-to-have | keys on `source_id` | `tests/e2e/test_multi_source_same_type.py` |

Full map with every file: [docs/00_architecture.md](docs/00_architecture.md#requirements-map).

## What is deliberately not built

- Alembic migrations: `create_all` at startup, and startup stops if an existing table is missing a column.
- Auth beyond a per-tenant API key and a shared bootstrap token.
- Real Play Store, Twitter and Intercom API clients: those sources are push-only, tested with fixtures.
- Language detection: `language` is filled when the source sends it (Play Store, Twitter), else empty.
- A UI, Kafka or Redis, and a Docker image.
- Twitter delete events: they fail validation and go dead; the tweet stays visible.
- Intercom deletions and redactions: unsupported topics go dead on purpose, so a privacy request is not dropped silently.
- Pull-side deletions: Discourse search never returns deleted posts, so a deleted forum post stays visible.
