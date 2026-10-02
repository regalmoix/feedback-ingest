# Phase 4 — Pull integration (Discourse)

Status: implemented 2026-10-03 (commits 301a023 / a5f708f, merged), review fixes applied. Depends on Phases 2–3 and ADR-003.

## What this phase builds, in one paragraph

The second way in. For sources we poll instead of receiving webhooks, a `PullService` asks the source's
connector for pages of payloads, feeds every payload through the same `IngestionService.accept` as a webhook
would, and only after a page's raw rows are committed does it store that page's cursor on the source row. A
scheduler thread runs this for every pull-mode source every N seconds; an endpoint triggers it on demand (and
is the demo button). Push and pull therefore share the queue, the worker, the retry logic and the idempotency
rule. The Discourse connector's `pull` already exists from Phase 2; this phase adds the service, the scheduler,
the endpoint, and a live test.

## Glossary
- Cursor: a bookmark the connector owns (for Discourse an ISO timestamp) saying "I have seen everything up to
  here". Stored on the `Source` row.
- Overlap window: we move the bookmark back 60 seconds so items that arrive at the boundary are fetched twice;
  the unique key makes the second copy harmless.
- Tick: one scheduler pass over all pull sources.

## Services
`services/pull.py` — `PullService(sources: SourceStore, ingestion: IngestionService, http: HttpClient, clock: Clock)`
- `sync(source: Source) -> PullResult(pages: int, accepted: int, duplicates: int, cursor: str | None, error: str | None)`:
  ```
  puller = PULLERS[source.type]            # KeyError → ConfigError (checked at source creation too)
  for page in puller.pull(source, http, clock.now()):
      for payload in page.payloads: ingestion.accept(source, payload)   # each is its own commit
      sources.update_cursor(source.id, page.cursor)                      # only after the page's rows exist
  ```
  `TransientError` (429/5xx/network) stops the loop; pages already committed keep their cursor; the error is
  returned in `PullResult.error` and logged at WARNING with `source_id`, `tenant_id`. Any other exception is
  logged at ERROR and returned the same way; the scheduler must never die because one source is broken.
  `# ponytail: whole-page accept loop; batch enqueue if a page ever holds thousands of items`.
- `sync_all() -> list[PullResult]`: `for source in sources.list_by_mode(SourceMode.pull)` (enabled only, see Phase 5) → `sync`.

`services/scheduler.py` — `SchedulerService(pull: PullService, interval_seconds: float)`
- Same thread/Event shape as `WorkerService`: `start()`, `stop()`, `alive`, `run_once()` = `pull.sync_all()`.
- Started in the app lifespan when `settings.scheduler_enabled` (new setting, default True); `/health` reports
  `scheduler_alive` too.

## API
`api/sources.py` (full CRUD arrives in Phase 5; this phase adds only the trigger)
- `POST /v1/sources/{source_id}/sync` → tenant + source checks → `pull.sync(source)` → `200 PullResult`.
  404 for push-only sources (`type not in PULLERS`) with a clear detail. Runs inline (sync endpoint), which is
  fine for a demo-sized page; `# ponytail: inline sync; enqueue a "sync job" if a backfill takes minutes`.

## Discourse specifics already in the connector (Phase 2), restated so the service is testable
- `source.config` keys: `base_url` (e.g. `https://meta.discourse.org`), `start_after` (ISO date used when
  `cursor` is None, e.g. `2021-01-01`), optional `page_size` (default 50). `config` is validated by
  `check_source` from ADR-003 at creation time: a pull source must have a puller and these keys.
- Cursor = ISO timestamp of the newest `created_at` seen minus 60 s; never moves backwards (`max(old, new)`).
- Search query: `after:{cursor_date} before:{today}`; pagination via `page=N` until a page returns fewer posts
  than the page size or no posts.
- Each page: one `search.json` call plus one `t/{topic_id}/posts.json?post_ids[]=…` call per distinct topic.
- Per-call errors from `HttpClient` are `TransientError` (429, 5xx, network, non-JSON) and stop the iterator.

## Tests
- `tests/unit/services/test_pull.py` (memory adapters + stub `HttpClient` keyed by URL):
  two pages → cursor equals page 2's cursor, `accepted` counts rows, duplicates counted when a payload is
  repeated; `TransientError` on page 2 → page 1's cursor persisted, `error` populated, page 2 not accepted;
  cursor never moves backwards; `sync_all` continues past a broken source and returns one result per source;
  push-only source → `ConfigError`.
- `tests/unit/services/test_scheduler.py`: `run_once` calls `sync_all`; thread start/stop; an exception in one
  tick does not stop the next.
- `tests/api/test_sync_api.py`: 401/404 paths; 200 with the result body; push-only source → 404.
- `tests/e2e/test_pull_to_query.py`: SQLite file, real worker, `HttpxClient(transport=httpx.MockTransport(...))`
  serving recorded Discourse-shaped JSON for `search.json` (two pages) and `posts.json`: `POST /sync` → wait →
  records exist with `kind=post`, `metadata.topic_id`; second `POST /sync` → `duplicates > 0`, record count unchanged.
- `tests/live/test_discourse_live.py` (`@pytest.mark.live`): real `HttpxClient` against `https://meta.discourse.org`
  with `start_after=2021-01-01` and the cursor window capped to a few days (connector honours
  `config["until"]` if present, else today) so the live test fetches a small, fixed window; asserts ≥1 record and
  that a second sync produces zero new records. Skipped by default; run with `uv run pytest -m live`.

## Files
```
feedback_ingest/services/{pull,scheduler}.py
feedback_ingest/api/sources.py (sync endpoint only)
feedback_ingest/config.py (+ scheduler_enabled, pull_interval_seconds already present)
feedback_ingest/main.py (+ scheduler lifecycle, health flag)
tests/unit/services/{test_pull,test_scheduler}.py  tests/api/test_sync_api.py
tests/e2e/test_pull_to_query.py  tests/live/test_discourse_live.py
tests/fixtures/discourse/{search_page1,search_page2,posts_topic_*.json}
```

## Deviations recorded
- `ConfigError` lives in `services/pull.py`, not in `domain/errors.py`. It stays a separate class
  because it maps to 409, while `NotFoundError` maps to 404.
- `PullResult` carries `source_id`, so `sync_all` results can be told apart.
- The `MockTransport` helpers (`discourse_http`, `add_pull_source`) live in `tests/helpers.py` (moved in Phase 6).
- Pull fixtures are under `tests/fixtures/discourse/pull/`.
- The scheduler waits one interval before its first tick.
- The sync endpoint is in `api/sync.py`, not `api/sources.py`.
- Review fixes: the sync endpoint answers 409 unless the source is an enabled pull source (was 404 for
  push-only); `sync_all` turns a `ConfigError` into that source's `PullResult.error`; a generic failure
  returns `"<ExceptionType> (see logs)"`; the cursor never moves backwards (connector and service both
  take the max); a window that needs more than 20 search pages raises instead of stalling silently; the
  live window is bounded by `config["window_days"]`, not `config["until"]`; `/health` is degraded when an
  enabled scheduler thread is dead.

## How to explain this phase in the interview
"Polling is just another producer. The connector returns pages; each page's payloads go through the exact same
accept call a webhook uses, and only then do we save that page's cursor. If Discourse rate-limits us halfway, we
keep the pages we already have and resume from their cursor next tick. The 60-second overlap means we'd rather
fetch a post twice than miss one, and the unique key makes the duplicate free. One scheduler thread ticks all
pull sources; one endpoint triggers a sync by hand, which is what I'll press in the demo."
