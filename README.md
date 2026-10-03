# Feedback Ingestion Service

A multi-tenant backend that ingests customer feedback from heterogeneous sources (Intercom, Play Store,
Twitter, Discourse, and a custom webhook that takes Enterpret's public record shape) by both push (signed
webhooks) and pull (polling Discourse's public API). The parsed JSON payload is saved in a `raw_events`
table before the API answers 202 (not the raw bytes, so the signature cannot be re-checked from storage; a
pulled Discourse post also carries the topic title we add). A background worker transforms each one into a uniform, de-duplicated `FeedbackRecord` that keeps common fields (kind, text, author, language,
rating, tenant, source) plus typed source-specific metadata. Failures retry with backoff, then park in a
dead list that can be replayed.

## Read in this order

1. [Architecture](docs/00_architecture.md): diagrams, module map, requirements map
2. [Whiteboard script](docs/interview/whiteboard.md)
3. [Demo script](docs/interview/demo_script.md) (what to say at each step of `scripts/demo.sh`)
4. [Glossary](docs/interview/glossary.md)
5. Decisions: [ADR-001 storage and queue](docs/decisions/ADR-001-storage-and-queue.md),
   [ADR-002 record and idempotency](docs/decisions/ADR-002-uniform-record-and-idempotency.md),
   [ADR-003 connectors](docs/decisions/ADR-003-connector-abstraction.md)

Reference: [Q&A bank](docs/interview/qa_bank.md) (likely questions with short answers),
[failure scenarios](docs/interview/failure_scenarios.md),
[firefight runbook](docs/interview/firefight_runbook.md), [alternatives](docs/interview/alternatives.md),
[extensions](docs/interview/extensions.md) (recipes for "how would you add X?"),
[debt ledger](docs/interview/debt_ledger.md) (every `ponytail:` shortcut and when to fix it),
[research](docs/research/) (public Enterpret notes and the tailoring rules), and, historical (superseded where
the code differs), the [plan](docs/PLAN.md) and the phase docs:
[01 domain, ports, adapters](docs/phases/01_domain_ports_adapters.md),
[02 connectors](docs/phases/02_connectors.md), [03 push API and worker](docs/phases/03_push_api_and_worker.md),
[04 pull](docs/phases/04_pull_integration.md), [05 tenancy, query, seed, demo](docs/phases/05_tenancy_query_seed_demo.md),
[06 hardening and interview pack](docs/phases/06_hardening_interview_pack.md). How this was built:
[AGENT_WORKFLOW.md](AGENT_WORKFLOW.md).

## Run

```sh
uv sync
uv run pytest
FI_BOOTSTRAP_TOKEN="$(openssl rand -hex 32)" uv run uvicorn feedback_ingest.main:app
```

`POST /admin/tenants` is refused (401) while `FI_BOOTSTRAP_TOKEN` is the default `change-me` or empty, and
startup logs a warning saying so. Gates before any commit:
`uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`.

## Demo

`scripts/demo.sh` (needs `uv`, `curl`, `jq`, `openssl`; uses `demo.db` and port 8000; exports a random
`FI_BOOTSTRAP_TOKEN`) runs the whole story:

1. Starts the server and shows `/health`.
2. Seeds two synthetic tenants: `lumenote` (consumer app: a Discourse pull source, two Play Store and one custom push source) and `brightwave` (B2B SaaS: Intercom, Twitter and custom push sources).
3. Pushes the same signed Play Store review twice: `duplicate=false`, then `duplicate=true`.
4. Pushes it to a second Play Store source of the same tenant.
5. `lumenote` sees two review records (same `external_id`, two sources, with rating, language and Play Store metadata); `brightwave` sees none.
6. One custom webhook batch becomes three records of three kinds; `kind=survey` lists the survey.
7. `brightwave` pushes an Intercom conversation and a tweet; both come out in the same record shape.
8. A malformed payload goes dead; replay runs it again and it goes dead again.
9. A live Discourse sync against meta.discourse.org (2021-01-01 to 2021-01-05) and the resulting posts.
10. Twenty pushes queued with the worker off, `kill -9`, restart: the backlog drains.
11. Stops the server.

`uv run pytest -m live` runs the live Discourse test (`tests/live/test_discourse_live.py`, needs network).

## Design

Three guarantees: **durable before ack** (the API answers 202 only after the `raw_events` row commits, 503 if
it cannot), **idempotent upsert** (database unique keys on source plus the source's own id, not application
checks), and **replay from raw** (the stored payload can be run again through a fixed connector). Everything
else, with diagrams, is in [docs/00_architecture.md](docs/00_architecture.md).

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
| `FI_PULL_DEADLINE_SECONDS` | `60` | Time budget for one sync; past it the pull stops at the last saved page |
| `FI_HTTP_MAX_BYTES` | `2000000` | Largest upstream response the HTTP client reads |
| `FI_SCHEDULER_ENABLED` | `true` | Start the pull scheduler |
| `FI_BOOTSTRAP_TOKEN` | `change-me` | Guards `POST /admin/tenants`; the default and the empty string are refused (401), and startup warns |

`scripts/seed.py` reads `FI_BASE_URL` (default `http://127.0.0.1:8000`) and needs `FI_BOOTSTRAP_TOKEN`; it
writes the keys and secrets to `.seed.json` (mode 600) and prints only the path. `scripts/sign.py <body file>`
reads the secret from `FI_SIGN_SECRET` and prints the `X-Signature` value; it only signs.

## API

| Route | Auth | Purpose |
|---|---|---|
| `GET /health` | none | Worker and scheduler liveness, `failing_sources` (a count), global queue counts; 503 when either thread is dead, or the worker has made no progress for about 10 s, or storage is down (the scheduler is only checked for being alive); never for a failing source |
| `POST /admin/tenants` | `X-Bootstrap-Token` | Create a tenant; returns its API key once; 401 while the server's token is the default or empty |
| `POST /v1/sources` | `X-API-Key` | Create a source; a push source gets a webhook secret, shown once (a chosen one needs 16+ chars); a pull source cannot have one (422) |
| `GET /v1/sources` | `X-API-Key` | List the tenant's sources, secrets masked |
| `GET /v1/sources/{id}` | `X-API-Key` | One source |
| `PATCH /v1/sources/{id}` | `X-API-Key` | `enabled` and/or `config` (merged key by key and re-checked, 422 if invalid), for example a smaller `window_days` |
| `POST /v1/sources/{id}/events` | `X-Signature` only, no API key | Push webhook, two checks: the source id picks the source, HMAC-SHA256 of the raw body with that source's secret proves the sender. 404 unknown source; 409 for a pull source (webhooks are push-only); 401 bad signature; then 409 if disabled; 400 if not a JSON object; 202 with `raw_event_id` (the stored row, also on a duplicate) and `duplicate` |
| `POST /v1/sources/{id}/sync` | `X-API-Key` | Pull now; returns pages, accepted, duplicates, cursor, error; 502 when `error` is set; 409 if not an enabled pull source or already syncing |
| `GET /v1/records` | `X-API-Key` | Query records: `source_id`, `kind`, `since`, `limit`, `include_deleted` |
| `GET /v1/records/{id}` | `X-API-Key` | One record |
| `GET /admin/raw-events` | `X-API-Key` | Raw events by `status` (default `dead`), newest first, `limit` |
| `GET /admin/raw-events/{id}` | `X-API-Key` | One raw event with its payload and error |
| `POST /admin/raw-events/{id}/replay` | `X-API-Key` | Back to `pending` with attempts reset; 409 while a worker holds a live lease |
| `POST /admin/raw-events/replay` | `X-API-Key` | Bulk replay of the tenant's rows: `status` (`dead`, `failed` or `processed`, default `dead`), optional `source_id`, `limit` (default and max 500); returns `{"replayed": n}` |
| `GET /admin/queue` | `X-API-Key` | The tenant's raw-event counts per status |

A source or event id that belongs to another tenant answers 404 (bulk replay with a foreign `source_id` simply matches nothing). Any body over 1 MiB answers 413. Storage
down answers 503.

Sources (`type` on `POST /v1/sources`): `discourse` (push or pull), `playstore`, `twitter`, `intercom` (only
`conversation.*` snapshot topics are transformed, `ping` is skipped, anything else goes dead), and
`custom`. A `custom` source's webhook body is Enterpret's public shape, `{"records": [{"id", "type",
"createdAt", "text", "title"?, "author"?, "language"?, "rating"?, "updatedAt"?, "metadata"?}]}`, with
`createdAt` in epoch seconds (or milliseconds), flat string/number/bool `metadata`, and `type` one of `REVIEW`,
`CONVERSATION`, `FORUM_CONVERSATION_THREAD`, `SURVEY` (kinds review, conversation, post, survey). One push is
one raw event; any other `type` sends the batch to the dead list.

## Assignment

 [docs/problem_statement.pdf](docs/problem_statement.pdf). It asks for a service that ingests
feedback from heterogeneous sources (Intercom, Play Store, Twitter, Discourse posts) by push and pull, keeps
each source's own metadata (app version, country, ...), serves many tenants, and transforms everything into
one uniform structure with feedback types (reviews, conversations, ...) and common attributes (language,
tenant, source); it gives Discourse's search and posts APIs to test pulling, adds de-duplication and several
sources of one type per tenant as good-to-haves, and judges code quality, coverage of the requirements and
how easy it is to add a source.

## Status of requirements

| Requirement | Level | Where | Proved by |
|---|---|---|---|
| Heterogeneous sources | Must | `connectors/` | `tests/unit/connectors/` |
| Push and pull | Must | `api/ingest.py`, `services/pull.py`, `services/scheduler.py` | `tests/e2e/test_push_to_query.py`, `tests/e2e/test_pull_to_query.py` |
| Source-specific metadata | Must | `domain/metadata.py` | `tests/unit/test_models.py` |
| Multi-tenancy | Must | `api/deps.py`, `adapters/sqlalchemy/tables.py` | `tests/adapters/contract_stores.py`, `tests/api/test_records_api.py`, `tests/api/test_tenants_api.py` |
| Uniform structure, record types, common attributes | Must | `domain/models.py` | `tests/unit/connectors/test_contract.py` |
| Idempotency | Good-to-have | UNIQUE keys, `SqlFeedbackStore.upsert` | `tests/e2e/test_push_to_query.py`, `tests/adapters/contract_upsert.py` |
| Several sources of one type per tenant | Good-to-have | keys on `source_id` | `tests/e2e/test_multi_source_same_type.py` |

Full map with every file: [docs/00_architecture.md](docs/00_architecture.md#requirements-map).

## What is deliberately not built

The one authoritative list; the debt ledger and the Q&A bank link here. Shortcuts with a `# ponytail:` marker
in the code are in [debt_ledger.md](docs/interview/debt_ledger.md) instead.

Not built:

- Alembic migrations: `create_all` at startup, and startup stops if an existing table is missing a column.
- Auth beyond a per-tenant API key and a shared bootstrap token.
- Per-tenant fairness, quotas and rate limits: one tenant's burst sits ahead of others in the shared queue (the noisy-neighbour risk). The upgrade is round-robin claiming by tenant, or per-tenant partitions, plus a per-tenant rate limit.
- PII redaction before storage: raw payloads keep personal data; we only keep it out of logs and error text.
- Retention and erasure: raw payloads are kept forever, and a tombstone is not legal erasure.
- Secrets at rest: webhook secrets are plain text in the `sources` table (they must be readable to check the HMAC). Encrypt them, or keep them in a secret manager, before real customers.
- A timestamp in the webhook signature: a captured, correctly signed request can be sent again. It changes nothing (it is a duplicate raw event); a signed timestamp with a short window is the fix if replays matter.
- Real Play Store, Twitter and Intercom API clients: those sources are push-only, tested with fixtures. Google Play has no review webhook (reviews are polled from its API), so the fixtures stand in for that poller. The Twitter webhook CRC handshake is not built either.
- Language detection: `language` is filled when the source sends it (Play Store, Twitter, custom), else empty.
- Health and process counters (metrics, queue age), and source or time filters on the dead list.
- A UI, Kafka or Redis, and a Dockerfile.
- Twitter delete events: they fail validation and go dead; the tweet stays visible.
- Intercom redactions: `conversation_part.redacted` is an unsupported topic and goes dead on purpose, so a privacy request is not dropped silently. `conversation.deleted` is not special-cased: it goes dead on validation, or upserts if it carries a full conversation.
- Pull-side deletions: Discourse search never returns deleted posts, so a deleted forum post stays visible.

Kept on purpose (raised in review, kept with a reason):

- Adapter-level `limit` and `lease_seconds` guards (`claim`, `list_by_status`, `list_for_tenant` raise below 1). The API already validates them, but SQLite treats `LIMIT -1` as "no limit", and the adapters are also called from scripts, so the guard stays where the query is built.
- A per-connector `verify_signature` hook (ADR-003 ruling 3). Every connector delegates to the HMAC default today; the hook is where Intercom's SHA-1 or Discourse's prefixed header goes.
- Three Discourse modules (`discourse.py`, `discourse_models.py`, `discourse_pull.py`): one file would break the 120-line cap.
- Global queue counts on `/health` with no auth: they hold no tenant data; per-tenant counts are behind the API key at `GET /admin/queue`.
- The Discourse post URL is built from the upstream `topic_slug` as given: it is display data, never fetched by us.
- `kind` comes from one table (`KIND_BY_SOURCE` in `domain/enums.py`, filled in by `new_record`) rather than a class attribute on each connector.
- Pull treats permanent and transient upstream errors the same: stop, keep the cursor, retry next tick. A permanent error (for example a 404 `base_url`) retries every tick and shows in `failing_sources` until someone fixes the config.
