# Phase 4: Pull integration (Discourse)

Status: historical design record.

Status: implemented 2026-10-03 (commits 301a023 / a5f708f, merged), review fixes applied. Depends on Phases 2–3 and ADR-003.

**Update after Fleet 2 (commit cbb788c).** The code wins over this LLD. What changed here:
- `PullService(sources, ingestion, http, clock, deadline_seconds)`. `sync` sets a deadline (`now + FI_PULL_DEADLINE_SECONDS`, default 60) and calls `pull(source, http, clock, deadline)`. It saves each page cursor with `update_cursor(source.id, source.tenant_id, cursor)`, keeping the later of the stored and the new cursor.
- A per-source lock (per process): a second sync of a source that is already syncing gets 409 from `POST /sync`, and the scheduler skips that source for the tick.
- Pull treats permanent and transient upstream errors the same today: stop, keep the cursor, put the message in `PullResult.error`, retry on the next tick. Any other exception propagates: 503 from the endpoint if storage is down, otherwise 500.
- The scheduler lists sources with `list_enabled(SourceMode.PULL)` (was `list_by_mode`). `/health` no longer goes degraded because a source failed; it reports `failing_sources` as a count and returns 503 only for an unhealthy worker or scheduler thread.
- Discourse stops after 10 search pages (about 500 posts per day) and moves its cursor only on the final page of a window. `HttpxClient` follows no redirects and caps a response at `FI_HTTP_MAX_BYTES`.

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
`services/pull.py`: `PullService(sources: SourceStore, ingestion: IngestionService, http: HttpClient, clock: Clock)`
- `sync(source: Source) -> PullResult(pages: int, accepted: int, duplicates: int, cursor: str | None, error: str | None)`:
  ```
  puller = PULLERS[source.type]            # check_source guarantees a pull source has a puller
  for page in puller.pull(source, http, clock, deadline):               # built signature (Fleet 2)
      for payload in page.payloads: ingestion.accept(source, payload)   # each is its own commit
      sources.update_cursor(source.id, source.tenant_id, page.cursor)   # only after the page's rows exist
  ```
  `TransientError` (429/5xx/network) stops the loop; pages already committed keep their cursor; the error is
  returned in `PullResult.error` and logged at WARNING with `source_id`, `tenant_id`. Any other exception is
  logged at ERROR and returned the same way; the scheduler must never die because one source is broken.
  `# ponytail: whole-page accept loop; batch enqueue if a page ever holds thousands of items`.

`services/scheduler.py`: `SchedulerService(pull: PullService, interval_seconds: float)`
- Same thread/Event shape as `WorkerService`: `start()`, `stop()`, `alive`, each tick calls `pull.sync` for every `sources.list_enabled(SourceMode.PULL)` source (named `list_by_mode` before Fleet 2).
- Started in the app lifespan when `settings.scheduler_enabled` (new setting, default True); `/health` reports
  `scheduler_alive` too.

## API
`api/sources.py` (full CRUD arrives in Phase 5; this phase adds only the trigger)
- `POST /v1/sources/{source_id}/sync` → tenant + source checks → `pull.sync(source)` → `200 PullResult`.
  404 for push-only sources (`type not in PULLERS`) with a clear detail. Runs inline (sync endpoint), which is
  fine for a demo-sized page; `# ponytail: inline sync; enqueue a "sync job" if a backfill takes minutes`.

## Discourse specifics already in the connector (Phase 2), restated so the service is testable

As first designed. The built rules are in Phase 2 and the note at the top: no `page_size`, a bounded window
(`window_days`), at most 10 search pages, and the cursor moves only on the final page.

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
  cursor never moves backwards;
  push-only source → refused (built: the endpoint answers 409, and `check_source` stops a pull source without a puller).
- `tests/unit/services/test_scheduler.py`: thread start/stop; an exception in one
  source does not stop the next source, and one in a tick does not stop the next tick.
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
- The separate config error class is gone (Phase 6). The sync endpoint answers 409 for a source that is not an enabled pull
  source, and `check_source` guarantees every pull source has a puller, so `PullService.sync` simply indexes
  `PULLERS[source.type]`.
- `PullResult` carries `source_id`, so results can be told apart.
- The `MockTransport` helpers (`discourse_http`, `add_pull_source`) live in `tests/helpers.py` (moved in Phase 6).
- Pull fixtures are under `tests/fixtures/discourse/pull/`.
- The scheduler waits one interval before its first tick.
- The sync endpoint is in `api/sync.py`, not `api/sources.py`.
- Review fixes: the sync endpoint answers 409 unless the source is an enabled pull source (was 404 for
  push-only); the cursor never moves backwards (connector and service both take the max); a window that
  needs more than 10 search pages (Discourse rejects page 11) raises instead of stalling silently; the
  live window is bounded by `config["window_days"]`, not `config["until"]`; `/health` is degraded when an
  enabled scheduler thread is dead.
- Phase 6 error handling: `sync` catches only `TransientError` and `PermanentError` and puts `str(exc)` in
  `PullResult.error`; any other exception propagates (503 from the endpoint, `scheduler tick failed` in the
  log). `POST /sync` answers 502 with the `PullResult` when `error` is set. The scheduler keeps the latest
  tick's errors per source. (Superseded by Fleet 2: `/health` shows `failing_sources` as a count and
  stays "ok"; only an unhealthy thread makes it 503.) A search response without
  `grouped_search_result` is a `TransientError`, never read as the last page. `run_once` on the scheduler
  is gone; the loop calls `sync` per source.
- Phase 6 closing: the one-call "sync every source" method is gone. The scheduler loop syncs each source in its own `try`; an
  unexpected exception is logged (`scheduled sync failed`, with `tenant_id` and `source_id`) and recorded as
  counted as failing, and the next source still runs. Onboarding pass: the scheduler keeps `failing_sources`, an
  int set once per tick (the `_sync_one` results summed); if listing sources fails, it is the number of pull
  sources last listed (at least 1). `/health` shows the latest tick.

## How to explain this phase in the interview
"Polling is just another producer. The connector returns pages; each page's payloads go through the exact same
accept call a webhook uses, and only then do we save that page's cursor. If Discourse rate-limits us halfway, we
stop and keep the cursor where it was; the next tick fetches the window again and the unique key drops what we
already have. The 60-second overlap means we'd rather
fetch a post twice than miss one, and the unique key makes the duplicate free. One scheduler thread ticks all
pull sources; one endpoint triggers a sync by hand, which is what I'll press in the demo."
