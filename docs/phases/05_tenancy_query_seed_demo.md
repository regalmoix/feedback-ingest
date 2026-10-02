# Phase 5 — Tenancy, sources and records API, seed, demo

Status: implemented 2026-10-03 (commits 301a023 / a5f708f, merged), review fixes applied. Depends on Phases 3–4.

## What this phase builds, in one paragraph

The parts a customer (tenant) actually touches: creating and listing their sources (including a second
Playstore app, which proves "multiple sources of the same type per tenant"), querying their uniform feedback
records across all sources with simple filters, and a seed script plus demo script that set up two tenants and
walk through every requirement end to end. Everything is tenant-scoped by the API key; tenant B can never see
tenant A's sources, records or raw events.

## Domain change
- `Source.enabled: bool = True`. Sources are disabled, never deleted (ADR-002: deleting and re-adding would
  re-ingest history as duplicates). `SourceStore.list_by_mode` returns enabled sources only;
  `SourceStore.set_enabled(source_id, tenant_id, enabled)` added to the port and both adapters.
- `check_source(source)` (ADR-003) lives in `connectors/registry.py` and is called by the create endpoint:
  pull mode requires a puller and the connector's required config keys; push mode requires a secret.

## API
`api/sources.py`
- `POST /v1/sources` body `SourceCreate(type, name, mode, config: dict[str,str] = {}, webhook_secret: str | None = None)`
  → generates `id = uuid4().hex`, for push mode generates a secret when none given (`secrets.token_hex(32)`),
  runs `check_source`, stores, returns `201 SourceCreated(id, type, name, mode, config, webhook_secret)` (the
  only time the secret is shown in clear; later reads mask it).
- `GET /v1/sources` → `list[SourceView]` (secret masked as `"***"`, includes `cursor`, `enabled`).
- `GET /v1/sources/{id}` → `SourceView` (404 across tenants).
- `PATCH /v1/sources/{id}` body `{enabled: bool}` → `SourceView`.
- `POST /v1/sources/{id}/sync` (from Phase 4) stays in this file.

`api/records.py`
- `GET /v1/records?source_id=&kind=&since=&limit=100&include_deleted=false` → `list[FeedbackRecordView]`
  (every column plus `metadata` as the JSON dict). Validation: `limit` 1..500, `kind` is the enum, `since` ISO
  datetime. 404 when `source_id` belongs to another tenant (checked via `sources.get`).
- `GET /v1/records/{id}` → one record, tenant-checked.

`api/tenants.py` (bootstrap only; no auth tier beyond a shared bootstrap token)
- `POST /admin/tenants` with header `X-Bootstrap-Token` equal to `settings.bootstrap_token` (default
  `"change-me"`, printed with a warning at startup when unchanged) → creates `Tenant(id, name, api_key_hash)`,
  returns `201 {id, name, api_key}` once. `# ponytail: shared bootstrap token; real deployments put this behind an ops identity`.

## Scripts
`scripts/seed.py` — runs against a live server (`FI_BASE_URL`, default `http://127.0.0.1:8000`) using `httpx`:
creates tenants "acme" and "globex"; for each: one Discourse pull source (`base_url=https://meta.discourse.org`,
`start_after=2021-01-01`, `until=2021-01-05`), two Playstore push sources ("acme-android", "acme-ios-wrapper"),
one Twitter push, one Intercom push. Prints a table of tenant → api_key and source → id/secret, and writes the
same to `.seed.json` (git-ignored) for `demo.sh`. Synthetic names only.

`scripts/demo.sh` — the rehearsal script (bash, uses `curl`, `jq`, `python3` for HMAC via `scripts/sign.py`):
1. start server in background (`uv run uvicorn … --port 8000`), wait for `/health`.
2. `uv run scripts/seed.py`.
3. push `tests/fixtures/playstore/review.json` to acme-android twice → print both 202s (`duplicate=false`, then `true`).
4. push the same fixture to acme-ios-wrapper → a second record with the same `external_id` (multi-source same type).
5. `GET /v1/records?kind=review` → 2 records; `GET` with globex key → 0 (tenancy).
6. push `malformed.json` → `GET /admin/raw-events?status=dead` shows it → `POST …/replay` → dead again (replay works; payload is really bad).
7. `POST /v1/sources/{discourse}/sync` → prints `accepted`, then `GET /v1/records?kind=post&limit=3`.
8. kill the server with `kill -9` while 20 pushes are queued (`FI_WORKER_POLL_SECONDS=2` makes the backlog visible), restart, show `/admin/queue` draining to `processed`.
9. stop server. Every step prints the command it ran so the user can copy it at the whiteboard.

## Tests
- `tests/api/test_sources_api.py`: create push source without secret → secret generated and returned once, masked
  on GET; create pull source missing `base_url` → 422 with the key named; create pull source for a push-only
  type → 422; list/get across tenants → 404; PATCH enabled=false → excluded from `list_by_mode` (scheduler skips it).
- `tests/api/test_records_api.py`: filters by `source_id`, `kind`, `since`; `limit` bounds; tombstones hidden
  unless `include_deleted=true`; tenant B cannot read A's record by id (404) or via `source_id` (404).
- `tests/api/test_tenants_api.py`: bootstrap token required; api key works on `/v1/sources` afterwards.
- `tests/e2e/test_multi_source_same_type.py`: two Playstore sources, same fixture → two records, distinct
  `source_id`, same `external_id`.
- `tests/unit/connectors/test_check_source.py`: the three validation rules.
- `scripts/` are exercised by `tests/e2e/test_demo_smoke.py`: runs `seed.py` against a `TestClient`-backed
  base URL? Simpler: seed logic lives in `scripts/seed_lib.py` as functions taking an `httpx.Client`; the test
  calls them with `TestClient` (which is an httpx client) and asserts the created objects. `demo.sh` is run by hand.

## Files
```
feedback_ingest/api/{sources,records,tenants}.py (+ schemas additions)
feedback_ingest/domain/models.py (Source.enabled)  feedback_ingest/ports/stores.py (+ set_enabled)
feedback_ingest/adapters/{sqlalchemy,memory}/stores.py  feedback_ingest/connectors/registry.py (check_source)
feedback_ingest/config.py (+ bootstrap_token)
scripts/{seed.py,seed_lib.py,sign.py,demo.sh}
tests/api/{test_sources_api,test_records_api,test_tenants_api}.py
tests/e2e/{test_multi_source_same_type,test_demo_smoke}.py  tests/unit/connectors/test_check_source.py
```

## Deviations recorded
- `FeedbackStore.get(record_id, tenant_id)` was added to the port for `GET /v1/records/{id}`.
- No `FeedbackRecordView`: the API returns `FeedbackRecord` itself.
- `SqlFeedbackStore` lives in `adapters/sqlalchemy/feedback_store.py`.
- `scripts/` is a package (`scripts/__init__.py`) so tests can import `scripts.seed_lib`.
- `demo.sh` runs uvicorn with `.venv/bin/python` directly so `kill -9` hits the server, not `uv`.
- `config["window_days"]` (4) bounds the seeded Discourse window instead of `config["until"]`.
- Review fixes: disabled sources refuse pushes and syncs (409); `check_source` checks a connector's
  `required_config` in both modes (Discourse `base_url`) and `pull_config` in pull mode (`start_after`),
  plus `window_days` and an http(s) `base_url` without credentials; unknown `/v1/records` query
  parameters are 422; tenant names are unique (409) and non-empty (422); startup warns when the bootstrap
  token is empty and refuses a database whose tables miss a column; `seed.py` writes `.seed.json` after
  each tenant and fails with the server's detail; `demo.sh` fails fast on any HTTP error, a dead server,
  an undrained queue or a sync error.
- Tailoring pass: the seeded tenants are now `lumenote` (Discourse `lumenote-community`, Playstore
  `lumenote-android` and `lumenote-android-beta`, custom `lumenote-surveys`) and `brightwave` (Intercom
  `brightwave-support`, Twitter `brightwave-x`, custom `brightwave-nps`), one source list per tenant in
  `seed_lib.TENANTS`; `demo.sh` gains step 6 (custom batch, `kind=survey`), so it has ten steps.

## How to explain this phase in the interview
"A tenant creates sources with their own API key; a source is one configured instance, so two Playstore apps are
two rows with their own secrets and cursors, and the same review id in both apps is two records. Every read
filters by the tenant on the key; cross-tenant ids come back 404, not 403, so we don't leak existence. The demo
script runs the whole story in two minutes: duplicate push, second app, tenancy, dead letter and replay, a live
Discourse pull, and a kill -9 restart that drains the backlog."
