# ADR-001: Storage and async processing shape

## Status
Accepted (council-reviewed, 2026-10-03)

## Context
The service takes in customer feedback from Intercom, Playstore, Twitter and Discourse. Some sources push to us (webhooks). Others we pull from on a timer (polling). Every tenant can have several sources, including several of the same type. Each payload must become one uniform feedback record, with no duplicates. The grading looks at code quality, how many requirements are covered, and how easy it is to add a new source. In the interview, every choice must hold up under "what if X goes down" questions.

## Decision
**Storage and queue shape (fixed)**
- **SQLite through SQLAlchemy 2.0.** The connection string comes from `DATABASE_URL`. Pointing it at Postgres needs no code change, except the claim query noted below.
- **A `raw_events` table is the durable queue.** Every inbound payload is saved exactly as received before we reply. A "durable queue" here means work that sits on disk and survives a crash.
- **We call it an inbox, or a durable log. Not an "outbox".** An outbox holds messages we will send out. This table holds what came in.
- **Push and pull share one pipeline.** Webhooks and the Discourse poller both write rows into `raw_events`. One in-process worker handles every row the same way. It does not know or care how the row arrived.
- **The API returns 202 only after the row is committed.** 202 means "saved, not finished yet". If the DB is down we return 503, and the sender retries.

**Ports and adapters (fixed by the owner, kept honest)**
- Every external interface sits behind a Protocol "port". A port is a small interface the core code calls. An "adapter" is the one class that does the real work behind it. The ports are: event store / queue, feedback record store, source instance store, outbound HTTP, clock, and `Connector`.
- **Each port must be used by at least one test through its in-memory fake.** A port with no test using it is a port we cannot defend.
- **`Connector` is the extensibility port.** It has three jobs: verify the request, fetch since a cursor, transform a payload into a record. Adding a source means one new Connector class plus one sample payload.
- **The clock port exists so retry and lease tests don't really sleep.** Say exactly that.
- **The queue port is named by what it promises:** `enqueue`, `claim`, `mark_processed`, `mark_failed`, `mark_dead`, `requeue`. Swapping to a broker means a new adapter **and** a different retry model. Kafka has no per-message delay. SQS uses visibility timeouts. We never call it "one adapter, nothing else changes".

**Technical fixes the council found (must be built)**
- **Claim a job in one SQLite-safe statement.** SQLite has no row locks, and SQLAlchemy silently ignores `with_for_update(skip_locked=True)` on SQLite. So the claim is:
  `UPDATE raw_events SET status='processing', lease_until=:lease, attempts=attempts+1 WHERE id=(SELECT id FROM raw_events WHERE (status='pending' AND next_attempt_at<=:now) OR (status='processing' AND lease_until<:now) ORDER BY next_attempt_at LIMIT 1) AND (status='pending' OR lease_until<:now) RETURNING *`.
  If no row comes back, someone else got it, so we try again. The repeated condition in the outer `WHERE` is the rowcount check. On Postgres, only this one query changes to `SELECT ... FOR UPDATE SKIP LOCKED`. (`RETURNING` needs SQLite 3.35 or newer.)
- **WAL mode and `busy_timeout` are turned on at connect time.** WAL lets readers work while one writer writes. `busy_timeout` makes a writer wait briefly instead of failing with "database is locked".
- **Sync SQLAlchemy sessions, run through a threadpool.** No aiosqlite. Mixing sync and async sessions is where the hours go.
- **Webhook signature is checked before the insert.** Unsigned or badly signed requests get 401 and are never stored.
- **Source instance is a first-class table.** One row per configured source. It holds tenant, source type, webhook secret (or a reference to it), and the poll cursor. The webhook URL carries the source instance ID. That is how a push maps to a tenant and a secret.
- **The poll cursor moves forward only after the raw rows are committed.** A crash mid-poll re-fetches a page. Dedupe absorbs the repeat. Nothing is skipped.
- **The dedupe key includes tenant and source instance:** UNIQUE (`tenant_id`, `source_instance_id`, `external_id`). Two tenants with the same Intercom ID never collide.
- **Guard against out-of-order edits.** The upsert only overwrites when the incoming source `updated_at` is newer than or equal to the stored one. An old edit arriving late cannot overwrite a newer one.
- **Failures are sorted as permanent or transient.** Permanent means the payload will never work, for example bad shape or a failed validation. It goes to `dead` at once. Transient means it might work later, for example a timeout, a 429 or a locked DB. It retries with exponential backoff, and goes to `dead` after N attempts.
- **Per-tenant visibility on `/health` or an admin endpoint.** It shows backlog (pending count), dead count, oldest pending age and last error, per tenant and source instance.
- **Every log line carries `raw_event_id`.** One event can be traced from webhook to final record with a single grep.
- **Replay** puts dead rows back to pending. It can also re-run rows filtered by tenant, source instance and time window after a connector bug is fixed. Dedupe makes a re-run safe.

## Where the council agrees
- Durable-before-ack is the right core. Save the raw payload, then reply, then process.
- SQLite is fine for this scope, *if* the claim is a single conditional statement and WAL plus `busy_timeout` are on.
- Polled data must land in the same table as pushed data. One pipeline.
- The dedupe key must include tenant and source instance.
- "Swap to Kafka with one adapter" is false and will be broken in one question. Say "the retry model changes too".
- Scope is the real risk, not the storage choice. Every name and every abstraction needs a one-sentence answer.

## Where the council clashes
- **Ports.** Three advisors said cut every port except `Connector` (and maybe store and HTTP). The owner requires a port on every external interface. Resolution: keep them all. Make each one earn its place with a test that uses its fake. Present `Connector` as the extensibility story. Present the others as seams that keep a migration in one file, with honest limits on the queue port.
- **raw_events as a platform asset vs. scope discipline.** The Expansionist wanted the table pitched as an append-only log with reprocessing, enrichment and LLM stages. The others called that extra surface to defend. Resolution: adopt filtered replay. It reuses the same code path and gives the best firefight answer. Mention enrichment only as "what comes next". Do not build it.
- **Mentioning SKIP LOCKED.** The Expansionist said raise it unprompted. Others pointed out it does nothing on SQLite. Resolution: raise it only as "on Postgres, this one query becomes SKIP LOCKED". Never imply it runs today.
- **Clock port.** Called gold-plating by some. Kept, because the backoff and lease tests use the fake clock.

## Blind spots the council caught
- **Two workers will happen by accident.** `uvicorn --workers N` starts N copies of the in-process worker. The atomic claim keeps this safe. Say it before you are asked.
- **A slow transform can block the event loop** and delay 202 replies. Transforms run in the threadpool, not on the loop.
- **Noisy neighbours.** One tenant's 10k burst sits ahead of everyone else in a shared queue. Today, admit it and point at the per-tenant backlog numbers. Next step: claim round-robin by tenant.
- **Firefight visibility.** You need backlog, dead count and last error per tenant, plus logs keyed by event ID. Now in the Decision list.
- **Tenant resolution on push.** The webhook URL holds the source instance ID, and that row holds the tenant and the secret.
- **Upstream limits on pull.** A 429 or a quota hit is a transient failure. Back off and keep the cursor where it is.
- **Uniform record schema.** Decide which fields are shared columns and which go in a source-specific `metadata` JSON column. Store `connector_version` on each record, so a backfill can target only rows made by a buggy version.
- **PII retention.** Raw payloads hold personal data forever. State a retention rule, for example purge processed raw rows after N days. Leave it as a documented gap if it is not built.
- **Authorship.** Expect "did you write this?" Answer honestly. Show you can make a live change at the whiteboard.
- **One-command seeded demo.** Have one you have run and broken yourself.

## Rejected alternatives and why
- **Postgres via docker-compose:** more infra to run and explain. `DATABASE_URL` gets us there later with one query change.
- **Redis + arq/rq:** a second system to keep up. The DB table already gives durability, retries and replay by ID.
- **Kafka / SQS:** no per-message delayed retry or query-by-ID. That is heavy infra for a take-home, and it changes the retry model.
- **Synchronous inline processing:** a crash or slow transform loses events, or makes the sender time out. Nothing to replay.

## How to say it in the interview
**The one sentence:** "We save the raw payload to disk before we say yes. Everything after that is a retry or a replay."

- **DB is down?** → We can't save, so we return 503. The sender retries. Nothing was acknowledged, so nothing is lost.
- **Worker dies mid-event?** → The row stays `processing` with a lease end time. When the lease runs out, the next claim picks it up again. Dedupe makes the second run safe.
- **Duplicate webhook?** → The upsert hits the UNIQUE key (tenant, source instance, external ID). We end up with one record. Curl it twice and show it.
- **10k events at once?** → The API only does one insert per event, so 202s stay fast. The worker drains the backlog at its own pace. `busy_timeout` makes writers wait, not fail. One tenant's burst can delay others. That shows on the per-tenant backlog. Round-robin claiming is the next step.
- **Two workers?** → The claim is one conditional UPDATE. Only one worker can flip a row from pending to processing. The loser gets no row back and tries the next one. On Postgres that query becomes SKIP LOCKED.
- **Swap to Kafka?** → The queue port means the core code doesn't change. But I'd be honest: Kafka has no per-message delay, so retries move to retry topics. That's a new adapter plus a new retry model, not just a new adapter.
- **Why SQLite?** → Zero infra, and the grading is on code and extensibility, not ops. It allows one writer at a time. Past that, I change `DATABASE_URL` to Postgres and swap one claim query.
- **What did you not build?** → Per-tenant fair scheduling, a retention purge for raw payloads, real Twitter API access (we use recorded files), and enrichment stages. Each one is a known next step, not a surprise.

## The one thing to do first
Build the Intercom webhook end to end, with the real claim query and WAL on from day one. That means: verify signature, insert into `raw_events`, return 202, claim, transform, upsert. Then prove it with two tests: the same webhook twice gives one record, and two workers racing on one row gives exactly one claim.
