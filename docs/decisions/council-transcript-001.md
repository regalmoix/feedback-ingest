# Council Transcript 001: Storage and async processing shape

Date: 2026-10-03. Outcome recorded in ADR-001-storage-and-queue.md.

## Framed question
DECISION: Storage and async-processing shape for a take-home backend assignment ("ingest feedback records from heterogeneous sources: Intercom, Playstore, Twitter, Discourse; push (webhook) and pull (poll) models; multi-tenancy; transform to a uniform internal record with source-specific metadata; good-to-have: idempotency/de-dupe, multiple sources of the same type per tenant"). Evaluation criteria: code quality, number of requirements addressed, extensibility (how easy to add a new source). The candidate demos it in-office on a whiteboard with deep cross-questioning: design choices, what-ifs, "what happens when X goes down", real-life firefight scenarios with clients waiting. The candidate did not write the code themselves and needs to defend every choice in plain language.

PROPOSED: SQLite file via SQLAlchemy 2.0 (DATABASE_URL env lets it become Postgres unchanged), and a DB-backed outbox: every inbound payload is inserted verbatim into a raw_events table (status pending/processing/processed/failed/dead, attempts, next_attempt_at, lease) before the API returns 202; an in-process asyncio worker claims rows with a lease, transforms via a per-source connector, upserts into feedback_records (UNIQUE dedupe_key), retries with exponential backoff, dead-letters after N attempts, and an admin endpoint replays. All external interfaces (DB stores, queue, outbound HTTP, clock) sit behind Protocol "ports" with one SQLAlchemy/httpx adapter and one in-memory fake each, so swapping to Postgres/Kafka/SQS is a one-adapter change. Single process, zero infra to run.

ALTERNATIVES CONSIDERED: (a) Postgres via docker-compose from day one; (b) Redis + arq/rq worker; (c) Kafka/SQS style broker; (d) synchronous inline processing with no queue.

STAKES: A wrong shape either looks toy-like to senior interviewers or buries the candidate in infra they cannot explain. The design must survive "what if the DB is down / worker dies mid-event / duplicate webhook / 10k events arrive at once / two workers run".

## Fixed constraints from the project owner
- SQLite via SQLAlchemy 2.0 with DATABASE_URL, a raw-events table as the durable queue, in-process worker. Confirmed.
- A Protocol port + adapter around every external interface, so migrating DB or queue infra is a one-adapter change. Advice to cut ports is turned into guidance on keeping ports honest.
- Pull (Discourse) and push both feed the same raw-events table and worker pipeline.

## Advisor responses

### The Executor (Response A)
**Verdict: build it, but cut it down.** SQLite plus a DB-backed outbox is the fastest shape that gets through every "what if". Postgres, Redis or Kafka would add infra you'd have to explain without adding anything you can show. The risk is the ports layer, not the storage choice.

**Where the build gets stuck:**
1. **Two workers on SQLite.** SQLite has no `SELECT FOR UPDATE SKIP LOCKED`. Claim a row in one statement: `UPDATE raw_events SET status='processing', lease_until=? WHERE id=(SELECT id ... WHERE status='pending' AND next_attempt_at<=now LIMIT 1) RETURNING *`. Turn on WAL and `busy_timeout`, or you'll hit "database is locked" in the middle of the demo.
2. **Async SQLAlchemy plus aiosqlite.** Mixing sync and async sessions is where the hours go. Pick one. Sync sessions run with `run_in_threadpool` are fine.
3. **Too many ports.** A queue port is fake when the DB already is the queue. A clock port only earns its place if a test uses it. Every port you can't point to in a test is a question you can't answer. Keep only the store and HTTP ports.
4. **The pull side.** People forget that each source instance needs a saved cursor, keyed by (tenant, source_instance). The poller should write into the same `raw_events` table, so there is one pipeline, not two.
5. **Twitter.** You won't get API access. Use recorded test files and say so up front.

**What to do Monday morning:** Day 1: the Intercom webhook, end to end: verify the signature, insert into `raw_events`, return 202, transform, upsert, plus one test. Day 2: claim, lease, backoff, dead-letter, replay. Day 3: the poller and cursors. Day 4: the other two connectors. Time how long each new connector takes. That number is your extensibility answer.

**Demo scripts to rehearse:** curl the same webhook twice and show one row. kill -9 the process while processing, restart, show the row picked up again when its lease runs out. Send a burst of 10k events; the 202 stays fast because the API only inserts, and the backlog drains. Then say: "SQLite allows only one writer at a time. Past that limit I switch DATABASE_URL to Postgres and nothing else changes." DB down: the webhook returns 503 and the source retries. If you can't trace one event across the whiteboard without notes, you're not ready.

### The Outsider (Response B)
Reading this cold, the architecture isn't the main risk. The vocabulary is. The proposal uses "outbox," "lease," "ports," "adapters," "Protocol," "dead-letter" and "idempotency" in a few sentences. The candidate didn't write the code, so each of those words is a door the interviewer can open. Can the candidate explain each one in a single plain sentence, with no other jargon? If not, the word should go, or the thing it names should be cut.

1. **"Why is it called an outbox?"** Usually an outbox means saving a change and a message to send in the same transaction. Here nothing is being sent out. Payloads come in and get saved before work starts, which is an inbox. Using the wrong pattern name invites a correction in the first five minutes. Call it a "raw events inbox table."
2. **"Why have a queue in a single process?"** The most important plain answer: "202 means we saved it to disk, not that we finished. If processing crashes, the payload still exists and gets retried." Everything else follows from that sentence.
3. **"Who is waiting for the 202?"** Intercom's servers are, not a person. If the DB is down, return a 5xx and the sender retries. But Playstore reviews have no webhooks; they're polled. Does polled data go through the same table? If it does, say so out loud. Two ways in, one pipeline.
4. **"Why put the clock behind an interface?"** If the answer isn't "so the backoff tests don't sleep," remove it. Every abstraction with only a fake behind it looks like gold-plating.
5. **"Two workers on SQLite?"** SQLite locks the whole database for writes. That's fine, but the candidate has to say it plainly rather than imply row locks they don't have.
6. **"What's in dedupe_key?"** Tenant + source instance + external ID. If tenant isn't in it, one tenant's record can collide with another's.

**Verdict:** keep the shape and cut the words.

### The Contrarian (Response C)
**The weakest claim is "swapping to Kafka/SQS is a one-adapter change." It isn't, and a senior interviewer will break it in one question.** Your queue is a table you can query: per-row `next_attempt_at`, leases, replay by ID. Kafka has none of that. It has partitions, offsets and no per-message delayed retry. If you say "one adapter," you lose the room. Say this instead: "the outbox *is* the queue; moving to a broker changes the retry model, not just an adapter."

**SQLite will quietly give you a wrong answer to "two workers run."** SQLAlchemy drops `with_for_update(skip_locked=True)` on SQLite without any warning. So the tests pass on SQLite, and on Postgres the behavior changes. The claim must be a conditional `UPDATE ... WHERE status='pending' AND (lease expired) RETURNING id`, or a check that exactly one row was updated. If it's anything else, "Postgres unchanged" is false.

**10k events at once means "database is locked" errors.** SQLite allows one writer at a time. Do you have WAL mode and `busy_timeout` set? If not, the ingest endpoint returns 500s exactly when it is busiest.

**The pull path is missing from this design.** Where is the polling cursor stored for each source instance? What stops two processes from polling the same Playstore account? The outbox covers webhooks only. Half the assignment has no story.

**What exactly is the `dedupe_key`?** It must include tenant and source instance, or two tenants with the same Intercom conversation ID will overwrite each other. And when an edited Intercom conversation arrives out of order, an older version can overwrite a newer one. Does the upsert compare the source's `updated_at`?

**You will be asked to justify every port, and you can't.** Why is there a Clock port? Why a Queue port, when the queue is a DB table? Keep ports only where a second adapter really exists: the connectors. Present the rest as test seams, not as "swap anything."

**Smaller gaps:** Is the webhook signature checked before the insert? Payload errors that will always fail get retried until they hit the dead-letter state. Raw PII sits in `raw_events` forever with no retention rule.

### The Expansionist (Response D)
**The undervalued asset is the raw_events table.** Don't pitch it as a queue. Pitch it as an append-only log of exactly what each source sent. feedback_records is just a view built from it. That one shift turns a take-home into a real platform story.

1. **Reprocessing is the main feature, not the replay endpoint.** When a connector's transform has a bug, or product wants a new field like Playstore device model, you fix the connector and re-run it over the stored raw rows. You never re-fetch from Intercom and you lose nothing. In the "client waiting" firefight, the answer is: "Tell me the tenant, source and time window, I replay it, and dedupe_key makes that safe." Build replay to filter by tenant, source instance and time range, not just by dead rows.
2. **Push and pull share one pipeline.** The poller is just another producer that writes into raw_events, with a cursor per source instance. The worker never knows which model delivered a row. Multiple sources of the same type per tenant come for free.
3. **A connector test suite that defines the extension contract.** One shared test file every connector must pass: sample payload in, expected record out, same payload twice gives the same dedupe_key. "How do I add Zendesk?" becomes "one file, one sample payload, and the suite tells you when you're done."
4. **Point at what comes next.** Clean, uniform feedback records are what an enrichment step needs: sentiment, tagging, LLM classification. "Processed records can feed a second stage through the same pattern."
5. **The two-worker question is a chance to score.** On Postgres, `FOR UPDATE SKIP LOCKED` lets several workers claim different rows without collisions. Mention it unprompted.

### The First Principles Thinker (Response E)
You're asking which storage to use. The real question is what one rule the candidate can repeat under pressure that answers every "what if." Infrastructure isn't part of the grading. Code quality, requirement coverage and how easy it is to add a source are. So the design only has to do two things: make adding a connector trivial, and make every failure scenario reduce to the same sentence.

**That sentence is the outbox:** "We store the raw payload durably before we acknowledge it. Everything after that is a replay." DB down: 503, sender retries, nothing acknowledged and lost. Worker dies mid-event: lease expires, row claimed again. Duplicate webhook: UNIQUE constraint on (tenant_id, source_instance_id, external_id). 10k events: inserts are cheap, worker drains at its own pace. Keep the outbox. It's the right core.

**Cut most of the ports.** Fakes for the clock, the queue and HTTP add surface area the candidate didn't write and can't defend. "Swap to Kafka with one adapter" is a claim a senior interviewer will break in two questions: "How does your lease map to SQS visibility timeout? What about ordering?" The DB table *is* the queue, so a queue port with one implementation is a pretend abstraction. Keep exactly one Protocol, `Connector` (verify, fetch since cursor, transform). That's the extensibility criterion.

**The design question nobody is asking:** a "source" is a *configured instance*, not a type. Make source instances (tenant, type, credentials ref, poll cursor) a first-class table. That covers multiple sources per tenant, gives the dedupe scope, and gives pull-mode state a home. Pull mode is where weak designs fall apart: where does the cursor live, and what happens when a poll fails halfway through a page?

**SQLite is fine** if the candidate can say: "Claims are a conditional UPDATE with a rowcount check, WAL mode is on, there's one writer. On Postgres the claim becomes SKIP LOCKED, and here's the line that changes."

## Anonymisation mapping
A = The Executor, B = The Outsider, C = The Contrarian, D = The Expansionist, E = The First Principles Thinker

## Peer reviews
### Review by The Contrarian
1. Strongest: C. Only response that finds bugs that would break the demo: SQLAlchemy silently drops skip_locked on SQLite so tests pass while "Postgres unchanged" is false; older Intercom edit arriving late overwrites newer; always-failing payloads retried until dead-letter; signature check after insert; "one-adapter Kafka" claim falls apart (no per-message delay). E close behind for first-class source instance table.
2. Biggest blind spot: D. Sales pitch that never checks whether the design works; recommends mentioning SKIP LOCKED unprompted on a SQLite build; treats raw_events as permanent log without growth/PII retention/which connector version re-ran which rows; adds scope (enrichment, LLM) the candidate must defend.
3. All missed: noisy neighbours (one shared queue, one tenant's 10k burst delays all others); firefight visibility (backlog depth, lag per tenant, dead-letter counts, correlation ID per event); upstream limits (429s/quotas when polling, where pull credentials live).

### Review by The First Principles Thinker
1. Strongest: E. Starts from what is graded and the real constraint (candidate must defend code they didn't write). One sentence answering every what-if ("durable before ack; everything after is replay"). Cuts abstractions to the one serving extensibility (Connector). Source instance as first-class table covers multi-source, dedupe scope, cursor home. C close second on precision.
2. Biggest blind spot: D. Adds surface area (append-only log, enrichment, LLM, "platform story") against the main constraint; says bring up SKIP LOCKED unprompted which SQLAlchemy ignores on SQLite; never deals with SQLite single writer.
3. All missed: the uniform record schema itself: which fields are shared vs metadata JSON, how versioned, what happens when a new source doesn't fit. Extensibility judged on that more than the queue.

### Review by The Expansionist
1. Strongest: D. Only response treating raw_events as an asset: replay = reprocessing by tenant/source/time window, best firefight answer. Shared connector test suite makes extensibility demonstrable. E close second for source instances.
2. Biggest blind spot: B. Entirely defensive; never addresses extensibility or what makes the design stand out.
3. All missed: transform lineage (connector_version on every record so backfills target only buggy-version rows); live extensibility demo (generic JSON-webhook connector with field mapping); per-tenant fairness (round-robin claim by tenant).

### Review by The Outsider
1. Strongest: C. Names specific claims an interviewer would break with a fix for each. E's single rule should be borrowed.
2. Biggest blind spot: D. All pitch, no defence; SKIP LOCKED on SQLite trap; never questions ports/jargon; no failure scenarios; more vocabulary.
3. All missed: authorship ("did you write this?" needs an honest answer and a live change at the whiteboard); tenant resolution on push (how webhook maps to tenant+source instance: URL path, per-instance secret); visibility during a firefight (backlog depth, dead-letter count, per-tenant status endpoint, logs).

### Review by The Executor
1. Strongest: A. Only one you could follow on Monday: SQLite-safe claim query (single UPDATE ... RETURNING), WAL + busy_timeout, sync-vs-async trap, recorded files for Twitter, build order, demo scripts (kill -9, 10k burst). C close second (skip_locked silently dropped, out-of-order updates).
2. Biggest blind spot: D. Upside without cost; SKIP LOCKED on SQLite; never touches port cuts, write locking, signature checks.
3. All missed: two workers will happen anyway (uvicorn --workers N starts N in-process workers; CPU-heavy transform blocks the event loop and stalls 202s); no status view for the firefight (per-tenant backlog, dead count, last error, logs keyed by event ID); candidate needs a one-command seeded demo they have run and broken themselves.

## Chairman synthesis

Peer-review tally: The Contrarian (C) was named strongest by 2 of 5 reviewers (Contrarian, Outsider) and runner-up by 1 (Executor). The First Principles Thinker (E) was named strongest once and runner-up twice. The Executor (A) and The Expansionist (D) were each named strongest once, both by themselves. The Expansionist (D) was named the biggest blind spot by 4 of 5 reviewers. The verdict leans on C for correctness, E for framing, and A for build order. It takes one idea from D: filtered replay.

### Where the Council Agrees
- Durable-before-ack is the right core. Save the raw payload, reply 202, then process. All five advisors kept this shape.
- SQLite is fine for this scope, but only with a single-statement conditional claim (`UPDATE ... WHERE status='pending' AND next_attempt_at<=now ... RETURNING`, plus a check that one row came back) and with WAL mode and `busy_timeout` on. Without these, "two workers" and "10k burst" both fail in the demo.
- SQLAlchemy silently ignores `skip_locked` on SQLite. Tests would pass while the Postgres claim to be "unchanged" is false.
- The pull path must use the same `raw_events` table, with a cursor per source instance. One pipeline, two ways in.
- The dedupe key must include tenant and source instance.
- "Swap to Kafka/SQS with one adapter" is the weakest claim in the proposal. A broker changes the retry model (no per-message delay, no query by ID, visibility timeouts vs leases).
- Each piece of jargon and each abstraction is a door the interviewer can open. The candidate must explain each one in one plain sentence.

### Where the Council Clashes
- **Ports.** A, C and E said to cut most ports and keep only `Connector` (A would also keep the store and HTTP ports). The owner requires a port on every external interface, and that is not up for debate. Ruling: keep every port, but make each one honest. Every port is used by at least one test through its fake. `Connector` is presented as the extensibility port. The clock port is justified as "backoff tests don't sleep". The queue port is named by what it promises, and the candidate says plainly that a broker swap also changes the retry model. Dissent recorded: three advisors think the extra ports cost more defence time than they return.
- **Expansion vs. discipline.** D wanted `raw_events` pitched as an append-only log and a platform, with reprocessing, enrichment and LLM stages. C, E and four reviewers saw that as surface the candidate cannot defend. Ruling: adopt replay filtered by tenant, source instance and time window. It is cheap, it uses the same code path, and it is the best answer to "client is waiting". Enrichment is mentioned only as a next step.
- **SKIP LOCKED.** D said raise it unprompted. Everyone else noted it does nothing on SQLite. Ruling: mention it only as the one query that changes on Postgres.
- **Naming.** B said "outbox" is the wrong pattern name. Nobody disagreed. Ruling: call the table `raw_events`, and the pattern an inbox or durable log.

### Blind Spots the Council Caught
Raised in peer review, not in any first response:
- `uvicorn --workers N` starts N in-process workers. Two workers will happen by accident. The atomic claim is what makes this safe. (Executor)
- A CPU-heavy transform on the event loop stalls 202 replies. Run transforms in the threadpool. (Executor)
- Noisy neighbours: one tenant's burst delays every other tenant in a shared queue. (Contrarian, Expansionist)
- Firefight visibility: per-tenant backlog, dead count, last error, and logs keyed by event ID. Three of five reviewers raised it independently. (Contrarian, Outsider, Executor)
- Tenant resolution on push: the webhook URL names the source instance, and that row holds the tenant and secret. (Outsider)
- Upstream limits on pull: 429s and quotas, and where pull credentials live. (Contrarian)
- The uniform record schema itself: shared columns vs a metadata JSON column, versioning, and sources that don't fit. (First Principles)
- Transform lineage: `connector_version` on each record, so backfills target only rows from a buggy version. (Expansionist)
- Authorship honesty and a live whiteboard change. (Outsider)
- A one-command seeded demo the candidate has run and broken. (Executor)
Also from first responses and worth keeping: signature check before insert, permanent vs transient failures, out-of-order edits guarded by `updated_at`, PII retention (C), and recorded fixtures for Twitter (A).

### Recommendation
Build the proposed shape inside the owner's constraints: SQLite via SQLAlchemy 2.0, `raw_events` as the durable inbox, one in-process worker, and push and pull feeding one pipeline. Keep a port on every external interface, each one tested through its fake. These fixes are required:
1. Single-statement conditional claim with a rowcount check. It also reclaims expired leases.
2. WAL mode plus `busy_timeout`.
3. Sync sessions run through a threadpool. No aiosqlite.
4. Signature verified before insert.
5. A source instance table holding tenant, type, secret and cursor. The webhook URL carries the instance ID.
6. The cursor advances only after raw rows commit.
7. Dedupe on (tenant, source instance, external ID).
8. An `updated_at` guard against out-of-order edits.
9. Permanent failures go straight to dead. Transient ones get backoff.
10. Per-tenant backlog, dead count and last error on `/health` or an admin endpoint.
11. `raw_event_id` on every log line.
12. Replay filtered by tenant, source instance and time window.
Rejected: Postgres via docker-compose (infra without payoff), Redis/arq (second system), Kafka/SQS (wrong retry model, heavy), synchronous inline processing (no durability, nothing to replay). The line that answers every what-if: "We save the raw payload to disk before we say yes. Everything after that is a retry or a replay."

### One Thing First
Build the Intercom webhook end to end, with the real claim query and WAL on from day one: verify, insert, 202, claim, transform, upsert. Prove it with two tests: the same webhook twice gives one record, and two racing claims on one row give exactly one winner. Time how long the second connector takes. That number is the extensibility answer.
