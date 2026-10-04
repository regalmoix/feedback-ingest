# Study notes

Points from my own Q&A while learning the code: interview-relevant or non-obvious only. Short answers,
small examples. Newest at the bottom of each section.

## Design choices

**Can we swap the database, HTTP client or queue?**
Yes, within the port's promises. Services only call port methods, so a swap is one new adapter. Proof:
every store and queue port already has two implementations (SQLite and in-memory) passing the same
contract tests. SQLite to Postgres is easy. Table queue to Kafka is harder: the port promises "find event
by id" and "retry this one message later", which Kafka does not do natively, so the adapter must build
that or the port changes.

**Protocol vs abstract base class (ABC)?**
Both work. A Protocol is like a Java interface, but a class matches by having the right methods
("duck typing"); declaring it is optional. Chosen because test fakes need no inheritance and there is no
runtime machinery (mypy checks before the code runs). Every implementation still names its Protocol
(`class SqlSourceStore(SourceStore)`) so the IDE can jump to implementations and mypy flags drift at the
class line.

**Why random ids for tenants and sources instead of readable ones (like a domain)?**
Ids must never change and they are copied into every row; names and domains change, one company can own
several domains, and a random id in a URL leaks nothing. The readable label is the unique `name`
(`lumenote`). A readable "slug" could be added as a second unique column for nicer URLs.

**Why poll the queue every second instead of being notified?**
Simple and cannot lose work: the table is the truth. Cost: up to 1 s delay when idle. Upgrades, simplest
first: wake the worker in-process when an event is saved; Postgres LISTEN/NOTIFY; pub/sub (SNS, SQS,
Kafka); SQS in front of AWS Lambda. A notification is only a hint, so keep a slow poll as a safety net.
Lambda trade-offs: cold starts, a concurrency cap that can hammer the database, cost at steady volume.
(Their public engineering blog mentions Lambda and Step Functions.)

## Sources and auth

**What is a Source?**
One configured connection for one tenant: `type` (playstore, discourse, ...), `mode` (push = they call our
webhook, pull = we poll them), `config` (per-type settings), `webhook_secret`, `cursor`, `enabled`. A
tenant can have several sources of one type (two Play Store apps = two rows, different ids).

**How does the webhook secret work?**
It is shared between us and the sender, not private to us. We generate it when the source is created and
show it once. The sender signs each body with it (HMAC-SHA256, `X-Signature` header); we recompute and
compare. Wrong or missing signature: 401. Only push sources have one.

**Why does the webhook take no API key?**
Senders like Intercom can only be given a URL, not custom headers. The unguessable source id in the URL
picks the source, its signature proves the sender, and the tenant comes from the source row.

**Do we authenticate when we pull from Discourse?**
No: meta.discourse.org search is public. A private forum needs an API key in request headers; not built
(known gap). It would live with the source's settings, stored as a secret.

**What is `config` for?**
Per-type settings, not only for pull. Discourse needs `base_url` in both modes (to build post links); pull
also needs `start_after` and `window_days`. Play Store, Twitter, Intercom, custom: usually `{}`.

**What is the cursor?**
A bookmark of how far a pull source has read. With `start_after=2021-01-01`, `window_days=4`: first sync
reads 01-01..01-05 and the cursor becomes `2021-01-05T00:00:00`; next sync reads 01-05..01-09. If a sync
fails halfway, the cursor does not move and the window is re-read. A window reaching today ends at "newest
post minus 60 s": read a post twice rather than miss one; duplicates are dropped.

## The push path

**Webhook check order?**
Body over 1 MiB 413 (middleware, before the route) → source not found 404 → not a push source / no secret
409 → bad signature 401 → disabled 409 (after the signature, so only a proven sender learns it) → not a
JSON object, NaN or absurd nesting 400 → save → 202.

**Does the 202 wait for the save?**
Yes. `await run_in_threadpool(...)` waits; the thread only keeps the server free for other requests while
the blocking database write runs. 202 means "saved, not yet processed"; the worker turns it into a record
seconds later. If the database is down we answer 503 and never 202, so the sender retries.

**What does the sender do with the response?**
Mostly reads the status code: 2xx stop, 5xx retry, 4xx give up or alert. The body (`raw_event_id`,
`duplicate`) is for us and custom senders, e.g. look the id up in `/admin/raw-events/{id}`.

**`external_id` vs `external_event_id` vs our `id`?**
`external_id` is the source's own id for the item (like an ATS candidate id): `r1`. `external_event_id` is
that item at a version: Play Store `r1:<lastModified>`; it is the dedupe key for deliveries. Our `id` is
the internal unique key (external ids can clash across sources). A resend has the same key and is
dropped; an edit has a new time, so a new key, so it is kept and later updates the record. If the key were
only `r1`, edits would be lost. Exceptions: a custom batch is keyed by a hash of the whole body (the batch
is one delivery); an unreadable payload falls back to a body hash.

## The worker

**What does the worker do?**
A loop: claim a batch, process each event one by one, nap `poll_seconds` when idle. One failed round is
logged and retried; the thread does not die. `healthy` means alive AND made progress within
max(3 × poll, 10 s); a thread spinning on database errors shows unhealthy and `/health` returns 503.

**What is a claim and a lease?**
Claiming marks events `processing` with `lease_until = now + 30 s`. Other workers skip leased events. If the
worker crashes, the lease expires and another worker takes the event. Fencing: a late worker's
"mark done" is refused because the lease is no longer its own.

**Can two workers claim the same event at once?**
No. The claim is one statement that re-checks "still free?" while updating. On SQLite writes run one at a
time; on Postgres the repeated check handles it (SKIP LOCKED is the speed upgrade). Tested: 4 threads, 40
events, each claimed exactly once.

**What if processing takes longer than the lease?**
Assumed not: one event is milliseconds against 30 s. If it did, a second worker would process it too; the
save is idempotent (same key, same version) and fencing refuses the slow worker, so the cost is wasted
work, not wrong data. Lease renewal (heartbeat) is the upgrade; or raise `FI_LEASE_SECONDS`.

**What is `next_attempt_at`?**
"Not before this time." The claim only takes pending or failed events whose `next_attempt_at` is now or
earlier. A new event gets `now` (ready at once). After each failure it moves out with backoff: +2, +4, +8,
+16 s, and the 5th failure marks it dead (wait capped at `FI_BACKOFF_CAP_SECONDS`, 300). Replay sets it
back to `now` and resets attempts. Backoff avoids hammering a struggling upstream or database.

**In what order are events claimed? Is it fair across tenants?**
Up to `batch` (10) claimable events, earliest `next_attempt_at` first (oldest waiting work first).
Claimable = pending/failed and due, or processing with an expired lease. Not fair per tenant: if tenant A
dumps 10,000 events, tenant B waits behind them (noisy neighbour). Fix: round-robin claims per tenant or a
queue per tenant (their engineering blog describes per-tenant partitioning).

**How do our queue ideas map to SQS, Redis, Kafka?**
| Ours (SQLite table) | SQS | Redis | Kafka |
|---|---|---|---|
| Claim + lease | visibility timeout | XREADGROUP pending list | partition owner + offset |
| Lease expiry retries a crash | message reappears | XAUTOCLAIM stale entries | uncommitted offset re-read |
| Backoff via `next_attempt_at` | change visibility / delay | sorted set by retry time | retry topics (no per-message delay) |
| `status = dead` | dead-letter queue | separate stream | dead-letter topic |
| Lookup by id, per-tenant dead list | no | only if indexed yourself | no |

Say: "SQS is the closest swap. Kafka changes the retry model. Either way keep a small table for lookup and
replay."

**Memory queue vs SQLite queue: which to read?**
Learn behaviour from `adapters/memory/queue.py` (plain Python). Both pass the same contract tests, so the
behaviour matches. The SQLite version only adds database guarantees: the claim is one atomic
`UPDATE ... RETURNING`; `BEGIN IMMEDIATE` and the repeated check make two workers safe; a unique constraint
enforces the dedupe key; a composite foreign key refuses a row whose tenant does not own its source.

**Why two attempt-limit checks (`>=` in `_retry`, `>` in `process`)?**
They guard different paths. `_retry`'s `>=`: the 5th normal failure goes dead immediately, with the real
error. Without it the event waits another backoff (32 s, up to 300 s), shows as `failed` as if it will
retry, and dies only on the next claim. `process`'s `>` (checked before work): catches events whose
earlier attempts crashed before anything was recorded (process killed); the claim already counted those
attempts, so `> max` means "stop".

**How is a retry done? Do we re-enqueue?**
No. The row is the queue entry, so a retry is a status change: `_retry` marks it `failed` with
`next_attempt_at = now + min(2^attempts, 300 s)`, and the claim picks it up again when due. Contrast:
SQS keeps the same message but hides it longer (change its visibility timeout); Kafka cannot delay one
message, so you publish a copy to a retry topic and move on.

**When does an event retry and when does it go dead?**
Retry (`failed`): transient errors (upstream 503/timeout, database locked) and unknown exceptions (logged
with the traceback; stored error is only "<ErrorType> (see logs)"). Dead at once: validation failure
(payload missing a field), permanent errors (unsupported topic or record type, source not found). Dead
after 5 attempts: anything still failing. Say: "Bad data cannot get better, so it goes dead and waits for
a fix plus replay. Flaky failures retry with backoff. After 5 tries anything goes dead so nothing loops
forever." Unknown errors are retried on purpose (safe if transient); the upgrade is classifying more as
permanent once seen in production.

**What does "lease lost" mean?**
This worker's lease expired and another worker re-claimed the event before this one finished. Its
"mark done" is refused (fencing: status, attempts and lease must match the copy it claimed), it logs
"lease lost" and moves on. The row is not orphaned: the newer worker finishes it. Also happens if an
admin replays the event mid-work.

**Scaling and other worker questions?**
More processes (the claim is atomic); one process handles one event at a time. Thread not async because
the database calls block and one thread is simplest.

## Tenancy and storage

**Why does the pipeline use `sources.get(id, tenant_id=...)` and not `get_by_id` plus a check?**
Same result, but the tenant is part of the lookup, so the check cannot be forgotten and a wrong-tenant
source is simply "not found". House rule: every read that knows its tenant is tenant-scoped; `get_by_id`
exists only for the webhook, where the tenant is not known yet. SQLite also refuses such a row outright
(composite foreign key).

**Anything the SQLite stores do beyond the memory ones?**
Behaviour is the same (shared contract tests). Extras: webhook secrets are stored in plain text (known gap,
"secrets at rest": encrypt the column or use a secrets manager); tenant names and API-key hashes are unique
columns, so a duplicate becomes `ValueError` and then 409; tenant scoping is a `WHERE tenant_id = ...`.

## App structure (FastAPI)

**What is `AppState` / `Ctx`?**
Built once at startup, shared by every request: adapters, services, settings (one per process; `uvicorn
--workers 4` means 4 copies). Not thread-local (Flask `g` is per request); closer to Flask
`app.extensions`. Per-request values (the tenant) come through `Depends`. Safe to share because services
keep no per-request data and each database call has its own transaction.
