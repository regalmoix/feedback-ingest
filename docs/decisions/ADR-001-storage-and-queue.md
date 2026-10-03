# ADR-001: Storage and async processing shape

## Status
Accepted (council-reviewed, 2026-10-03)

## Context
The service takes in customer feedback from Intercom, Playstore, Twitter and Discourse. Some sources push to us (webhooks). Others we pull from on a timer (polling). Every tenant can have several sources, including several of the same type. Each payload must become one uniform feedback record, with no duplicates. The grading looks at code quality, how many requirements are covered, and how easy it is to add a new source. In the interview, every choice must hold up under "what if X goes down" questions.

## Decision
**Storage and queue shape (fixed)**
- **SQLite through SQLAlchemy 2.0.** The connection string comes from `FI_DATABASE_URL`. Moving to Postgres means: set `FI_DATABASE_URL`, add a driver, change three queries (claim, upsert, enqueue), add migrations.
- **A `raw_events` table is the durable queue.** Every inbound payload is saved exactly as received before we reply. A "durable queue" here means work that sits on disk and survives a crash.
- **We call it an inbox, or a durable log. Not an "outbox".** An outbox holds messages we will send out. This table holds what came in.
- **Push and pull share one pipeline.** Webhooks and the Discourse poller both write rows into `raw_events`. One in-process worker handles every row the same way. It does not know or care how the row arrived.
- **The API returns 202 only after the row is committed.** 202 means "saved, not finished yet". If the DB is down we return 503, and the sender retries.

**Ports and adapters (fixed by the owner, kept honest)**
- Every external interface sits behind a Protocol "port". A port is a small interface the core code calls. An "adapter" is the one class that does the real work behind it. Built as six ports, `TenantStore`, `SourceStore`, `FeedbackStore`, `RawEventQueue`, `HttpClient` and `Clock`, plus the `SourceConnector` Protocol as the extensibility seam.
- **Each port must be used by at least one test through its in-memory fake.** A port with no test using it is a port we cannot defend.
- **`Connector` is the extensibility port.** It has three jobs: verify the request, fetch since a cursor, transform a payload into a record. Built differently: adding a source is five small steps: (1) a `SourceType` value and its `KIND_BY_SOURCE` entry in `domain/enums.py`; (2) a metadata model in the `SourceMetadata` union in `domain/metadata.py`; (3) a connector file with its input model in `connectors/`; (4) its entry in `CONNECTORS` (and `PULLERS` if it pulls) in `connectors/registry.py`; (5) fixtures under `tests/fixtures/<type>/`. The contract test fails until all five exist. ADR-003 "How to add a new source" has the Zendesk example.
- **The clock port exists so retry and lease tests don't really sleep.** Say exactly that.
- **The queue port is named by what it promises:** `enqueue`, `claim`, `mark_processed`, `mark_failed`, `mark_dead`, `replay`. Swapping to a broker means a new adapter **and** a different retry model. Kafka has no per-message delay. SQS uses visibility timeouts. We never call it "one adapter, nothing else changes".

**Technical fixes the council found (must be built)**
- **Claim jobs in one SQLite-safe statement.** SQLite has no row locks, and SQLAlchemy silently ignores `with_for_update(skip_locked=True)` on SQLite. Built differently from the first draft: the claim takes a batch (`FI_CLAIM_BATCH`, default 10), and a `failed` row whose retry time has come is claimable too. "Claimable" means: (`pending` or `failed`, and `next_attempt_at <= now`) or (`processing`, and the lease has run out). The claim is one statement:
  `UPDATE raw_events SET status='processing', lease_until=:lease, attempts=attempts+1 WHERE id IN (SELECT id FROM raw_events WHERE <claimable> ORDER BY next_attempt_at LIMIT :batch) AND <claimable> RETURNING *`.
  The claimable test is repeated in the outer `WHERE`. So a row another worker took in between is skipped, not taken twice. On Postgres the inner `SELECT` would add `FOR UPDATE SKIP LOCKED`, so many workers do not wait on each other. (`RETURNING` needs SQLite 3.35 or newer.)
- **WAL mode and `busy_timeout` are turned on at connect time.** WAL lets readers work while one writer writes. `busy_timeout` makes a writer wait briefly instead of failing with "database is locked".
- **Sync SQLAlchemy sessions, run through a threadpool.** No aiosqlite. Mixing sync and async sessions is where the hours go.
- **Webhook signature is checked before the insert.** Unsigned or badly signed requests get 401 and are never stored. (Added later: the webhook takes no API key, and only push sources accept webhooks; a pull source answers 409. See ADR-003 ruling 8.)
- **Source instance is a first-class table.** One row per configured source. It holds tenant, source type, webhook secret (stored as plain text today; encrypting secrets at rest is a named gap), and the poll cursor. The webhook URL carries the source instance ID. That is how a push maps to a tenant and a secret.
- **The poll cursor moves forward only after the raw rows are committed.** A crash mid-poll re-fetches a page. Dedupe absorbs the repeat. Nothing is skipped. (Built: Discourse moves its cursor only on the final page of a search window, so a crash or error re-fetches the whole window.)
- **The dedupe key.** Superseded by ADR-002: records are `UNIQUE(source_id, external_id)`, and raw events are `UNIQUE(source_id, external_event_id)`. The first draft here was (`tenant_id`, `source_instance_id`, `external_id`). A source row belongs to exactly one tenant, so two tenants with the same Intercom ID still never collide.
- **Guard against out-of-order edits.** The upsert only overwrites when the incoming source `updated_at` is newer than or equal to the stored one. An old edit arriving late cannot overwrite a newer one.
- **Failures are sorted as permanent or transient.** Permanent means the payload will never work, for example bad shape or a failed validation. It goes to `dead` at once. Transient means it might work later, for example a timeout, a 429 or a locked DB. It retries with exponential backoff, and goes to `dead` after N attempts.
- **Per-tenant visibility on `/health` or an admin endpoint.** Built differently, and smaller: `GET /admin/queue` gives the calling tenant's raw-event counts per status. `GET /admin/raw-events` lists that tenant's dead rows, each with its error. `/health` shows global counts and `failing_sources`, a count of pull sources whose latest scheduled sync failed (no ids). The failing source ids are in the log lines. Oldest pending age and a stored per-source last error are not built.
- **Every worker and pipeline log line carries `raw_event_id`.** One event can be traced from webhook to final record with a single grep. The "accepted" line carries the stored id, also on a duplicate. Pull lines carry `tenant_id` and `source_id` instead, because a pull is not one event. Startup lines show "-" for the missing keys.
- **Replay** puts dead rows back to pending. Dedupe makes a re-run safe. Built: single replay (`POST /admin/raw-events/{id}/replay`) and bulk replay (`POST /admin/raw-events/replay?source_id=&status=&limit=`). Bulk replay works on the calling tenant's rows, filtered by source and by status (dead, failed or processed). A time-window filter is not built.

## Where the council agrees
- Durable-before-ack is the right core. Save the raw payload, then reply, then process.
- SQLite is fine for this scope, *if* the claim is a single conditional statement and WAL plus `busy_timeout` are on.
- Polled data must land in the same table as pushed data. One pipeline.
- The dedupe key must include tenant and source instance. (Built as `source_id` alone, ADR-002: the source already implies the tenant.)
- "Swap to Kafka with one adapter" is false and will be broken in one question. Say "the retry model changes too".
- Scope is the real risk, not the storage choice. Every name and every abstraction needs a one-sentence answer.

## Where the council clashes
- **Ports.** Three advisors said cut every port except `Connector` (and maybe store and HTTP). The owner requires a port on every external interface. Resolution: keep them all. Make each one earn its place with a test that uses its fake. Present `Connector` as the extensibility story. Present the others as seams that keep a migration inside the adapter layer, with honest limits on the queue port.
- **raw_events as a platform asset vs. scope discipline.** The Expansionist wanted the table pitched as an append-only log with reprocessing, enrichment and LLM stages. The others called that extra surface to defend. Resolution: adopt filtered replay. It reuses the same code path and gives the best firefight answer. (Built as bulk replay filtered by source and status.) Mention enrichment only as "what comes next". Do not build it.
- **Mentioning SKIP LOCKED.** The Expansionist said raise it unprompted. Others pointed out it does nothing on SQLite. Resolution: raise it only as "on Postgres, the claim query adds SKIP LOCKED". Never imply it runs today.
- **Clock port.** Called gold-plating by some. Kept, because the backoff and lease tests use the fake clock.

## Blind spots the council caught
- **Two workers will happen by accident.** `uvicorn --workers N` starts N copies of the in-process worker. The atomic claim keeps this safe. Say it before you are asked. All N processes read the same environment, so `FI_WORKER_ENABLED` cannot be off in only some of them. To have exactly one consumer, run separate processes, one with the worker on.
- **A slow transform can block the event loop** and delay 202 replies. Transforms run in the worker thread, never inside a request. The webhook's signature check, JSON parse and insert run in the threadpool, not on the loop.
- **Noisy neighbours.** One tenant's 10k burst sits ahead of everyone else in a shared queue. Today, admit it and point at the per-tenant counts from `GET /admin/queue`. Next step: claim round-robin by tenant.
- **Firefight visibility.** You need backlog, dead count and last error per tenant, plus logs keyed by event ID. Now in the Decision list (built as counts per tenant, the dead list with errors, and ids in logs).
- **Tenant resolution on push.** The webhook URL holds the source instance ID, and that row holds the tenant and the secret.
- **Upstream limits on pull.** A 429 or a quota hit is a transient failure. Back off and keep the cursor where it is. (Built: the pull stops, keeps the cursor, and retries on the next scheduler tick.)
- **Uniform record schema.** Decide which fields are shared columns and which go in a source-specific `metadata` JSON column. Store `connector_version` on each record, so a backfill can target only rows made by a buggy version.
- **PII retention.** Raw payloads hold personal data forever. State a retention rule, for example purge processed raw rows after N days. Leave it as a documented gap if it is not built.
- **Authorship.** Expect "did you write this?" Answer honestly. Show you can make a live change at the whiteboard.
- **One-command seeded demo.** Have one you have run and broken yourself.

## Rejected alternatives and why
- **Postgres via docker-compose:** more infra to run and explain. Getting there later means: set `FI_DATABASE_URL`, add a driver, change three queries (claim, upsert, enqueue), add migrations.
- **Redis + arq/rq:** a second system to keep up. The DB table already gives durability, retries and replay by ID.
- **Kafka / SQS:** no per-message delayed retry or query-by-ID. That is heavy infra for a take-home, and it changes the retry model.
- **Synchronous inline processing:** a crash or slow transform loses events, or makes the sender time out. Nothing to replay.

## How to say it in the interview
**The one sentence:** "We save the raw payload to disk before we say yes. Everything after that is a retry or a replay."

- **DB is down?** → We can't save, so we return 503. The sender retries. Nothing was acknowledged, so nothing is lost.
- **Worker dies mid-event?** → The row stays `processing` with a lease end time. When the lease runs out, the next claim picks it up again. Dedupe makes the second run safe.
- **Duplicate webhook?** → `raw_events` is `UNIQUE(source_id, external_event_id)`, so the second delivery is not stored again. It still gets 202, with `duplicate: true`. Records are `UNIQUE(source_id, external_id)`, so we end up with one record. Curl it twice and show it.
- **10k events at once?** → The API does one small write per event, so 202s stay fast. The worker drains the backlog at its own pace. `busy_timeout` makes writers wait, not fail. One tenant's burst can delay others. That shows in the per-tenant counts on `GET /admin/queue`. Round-robin claiming is the next step.
- **Two workers?** → The claim is one conditional UPDATE. Only one worker can flip a row to processing. The other worker simply does not get that row. On Postgres I would add SKIP LOCKED to the claim, so workers do not wait on each other.
- **Swap to Kafka?** → The queue port means the core code doesn't change. But I'd be honest: Kafka has no per-message delay, so retries move to retry topics. That's a new adapter plus a new retry model, not just a new adapter.
- **Why SQLite?** → Zero infra, and the grading is on code and extensibility, not ops. It allows one writer at a time. Past that, I set `FI_DATABASE_URL` to Postgres, add a driver, change three queries (claim, upsert, enqueue), and add migrations.
- **What did you not build?** → Per-tenant fair scheduling, a retention purge for raw payloads, real Twitter API access (we use recorded files), a stored per-source last error, and enrichment stages. Each one is a known next step, not a surprise.

## The one thing to do first
Build the Intercom webhook end to end, with the real claim query and WAL on from day one. That means: verify signature, insert into `raw_events`, return 202, claim, transform, upsert. Then prove it with two tests: the same webhook twice gives one record, and two workers racing on one row gives exactly one claim.
