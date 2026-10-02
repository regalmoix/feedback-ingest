# Council transcript 002: Uniform feedback record and idempotency

Date: 2026-10-03. Outcome: [ADR-002](ADR-002-uniform-record-and-idempotency.md).

## 1. Framed question

DECISION: The uniform internal record schema and idempotency key for a take-home backend assignment: "ingest feedback from heterogeneous sources (Intercom conversations, Playstore reviews, Twitter tweets, Discourse forum posts), push and pull, multi-tenant, transform to a uniform internal structure that supports different feedback types (reviews, conversations, ...), source-specific metadata (app-version from Playstore, country from Twitter, ...), and common record-level attributes (language, tenant, source). Good-to-have: idempotency/de-dupe; multiple sources of the same type per tenant (two Playstore apps for one tenant)." Evaluated on code quality, requirements covered, extensibility. Demoed in-office on a whiteboard under deep cross-questioning by the candidate, who did not write the code and must defend it in plain language.

PROPOSED:
- One `feedback_records` table with typed common columns: id, tenant_id, source_id, source_type, external_id, dedupe_key, kind (review|conversation|post|tweet), title, text, author, language (nullable, from source if provided), rating (nullable), source_created_at, source_updated_at, ingested_at, and `metadata` as a JSON column.
- `metadata` JSON validated at transform time by a per-source Pydantic model so it is typed at the edge but stored uniformly.
- `dedupe_key = sha256(tenant_id | source_id | external_id)` with a UNIQUE index; ingestion is an upsert; last-writer-wins only when the incoming `source_updated_at` is newer (or equal) than stored.
- Every inbound payload is kept verbatim in a `raw_events` table (also the processing queue) so records can be rebuilt/replayed after a transformer bug.
- Source is its own entity (id, tenant_id, type, name, mode push|pull, config, webhook_secret, cursor) so two Playstore apps = two source rows, and dedupe is per source.

ALTERNATIVES CONSIDERED: table-per-source-type; EAV/key-value metadata table; dedupe on content hash instead of external id; fully versioned/append-only records instead of upsert; language detection built in; a separate `conversations` parent entity for Intercom threads.

STAKES: Interviewers will probe: what if a source edits or deletes a post, what if external ids collide across apps, how do you query across sources, how does a new source with weird metadata fit, what breaks when the schema evolves.

Fixed constraints from the project owner (not re-litigated): one feedback_records table with typed common columns plus a JSON metadata column validated by per-source Pydantic models; Source is its own entity; raw payloads retained in raw_events (also the processing queue); SQLite via SQLAlchemy 2.0; Pydantic v2; mypy --strict.

## 2. Advisor responses

### The Outsider (Response A)
Here are the plain questions an interviewer will ask.

**"What is one record?"** For a Playstore review it's obvious. For an Intercom conversation it isn't. If a thread has 40 messages and a new reply comes in, does the upsert replace `text` with the whole thread joined together? Rejecting the `conversations` parent entity leaves this gap. Pick one answer, write it on the whiteboard first, and stick to it. "One conversation is one record, the messages live in metadata" is fine if you say it before they ask.

**"Why sha256?"** `UNIQUE(source_id, external_id)` does the same job with nothing to explain. A source row already belongs to a tenant, so having `tenant_id` in the hash adds nothing. The hash just invites the question "why hash at all?", and someone who didn't write the code will hesitate. Drop it, or have a one-line answer ready.

**"The tweet got deleted. Does my dashboard still show it?"** Nothing in the schema handles deletion. Add a `deleted_at` column and you can answer in one sentence.

**"What if the source doesn't send an updated time?"** Last-writer-wins relies on `source_updated_at`. When it's null, what happens? Say it out loud: a null loses to any stored timestamp, or else ingest time is used instead.

**"Why are `kind` and `source_type` both here?"** "tweet" is not a kind of feedback. It's a source. If `kind` holds tweet, it's just `source_type` under another name. Use review | conversation | post.

**"So I can't filter by language?"** If language is only filled in when the source provides it, the column will be mostly empty. Say that's a deliberate gap, not an oversight.

**The test:** can the candidate explain every column in one sentence without saying "it's for flexibility"? Any column that fails should be cut or have its sentence prepared.

### The Executor (Response B)
**Verdict: buildable in a day. These are the spots where the build will actually get stuck.**

1. **`metadata` is a reserved name.** SQLAlchemy's declarative `Base` already has `.metadata`, so a field with that name crashes at import. Fix: `source_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)`.
2. **Drop the sha256 `dedupe_key`.** `UNIQUE(source_id, external_id)` does the same job and is one less thing to defend. Since `source_id` already belongs to a tenant, external IDs can't collide across apps or tenants.
3. **The upsert is one statement:** `insert(...).on_conflict_do_update(index_elements=[...], set_=..., where=...)`. Two traps: tweets and many reviews have no `source_updated_at`; a plain `excluded.source_updated_at >= table.source_updated_at` evaluates to NULL and silently never updates. Wrap both sides in `COALESCE`, falling back to `source_created_at`. SQLite drops timezone info and compares datetimes as strings. Store naive UTC everywhere and normalize in the transformer.
4. **Pydantic to JSON:** use `model_dump(mode="json")`. Give each metadata model `source_type: Literal[...]` and a discriminated union, so mypy and the replay path can tell them apart.
5. **Deletes:** add a nullable `deleted_at` column (a tombstone). Don't hard-delete rows.
6. **`raw_events` as a queue:** SQLite has no `SKIP LOCKED`, so don't build a worker. Insert the raw event, transform and upsert in the same transaction, and set `processed_at`. A replay is a loop over `raw_events`. Point to the ceiling on the whiteboard: swap in a real queue when the load needs it.
7. **mypy --strict:** enable the `pydantic.mypy` plugin. Skip the old SQLAlchemy mypy plugin; 2.0 `Mapped[]` types work without it.
8. **Intercom:** store one record per conversation, with the parts in metadata. A new reply bumps `updated_at` and the upsert handles it. Skip the parent `conversations` entity.

**Monday order:** models plus `create_all`; the Playstore transformer; an upsert test: ingest twice, then an edit, then replay; the other three sources, each a copy of the pattern.

### The Expansionist (Response C)
**The biggest win here is `raw_events`, and the proposal treats it as a safety net.** Pitch it as the main design: `raw_events` holds the truth, and `feedback_records` is a view built from it that you can rebuild at any time. "What breaks when the schema evolves?" Nothing. Change the transformer and replay the stored payloads. Add `transformer_version` to each record so you can say "re-run only rows built by playstore-v1." That's one column.

**Add one nullable `parent_external_id` and you get threads in three sources.** Intercom conversation parts, Discourse replies and Twitter reply chains all have the same shape. One column gives you threading across sources without a `conversations` table.

**Leaving `language` nullable creates a slot for enrichment.** Name the stage: transform, then enrich, then store. Language detection, sentiment and topic tagging all plug in there later. This is a feedback-analytics company. Show them your ingestion layer is ready for their AI pipeline.

**The Pydantic metadata models give you a lot for free.** `model_json_schema()` produces a schema per source, so the system documents itself. In Postgres, often-queried fields like `metadata->>'app_version'` can become generated columns with an index: common columns for everything, plus promoted fields where speed matters.

**Deletes are a compliance feature, not an edge case.** Add `deleted_at` as a soft-delete marker that flows through the same upsert.

**For the demo, size the change for a new source.** Adding Reddit means one transformer, one metadata model and one registry entry. Put that list on the whiteboard.

### The Contrarian (Response D)
**The fatal flaw: your upsert assumes every payload is a full snapshot. Push payloads often aren't.**

1. **Partial webhooks destroy data.** An Intercom `conversation.user.replied` webhook carries the new message part, not the whole conversation. If last-writer-wins replaces `text` with that delta, the record now holds only the newest reply. You need to decide, and say out loud, whether a push is a trigger to re-fetch the full conversation or a delta you append.
2. **Twitter edits break dedupe on `external_id`.** An edited tweet gets a new tweet ID, and `edit_history_tweet_ids` points back to the original. Under your key, an edit becomes a duplicate record.
3. **There is no delete path.** No `deleted_at`, and an upsert never removes anything.
4. **The SHA-256 key does nothing.** `source_id` already implies the tenant, so `UNIQUE(source_id, external_id)` gives the same guarantee and is readable. Worse, keying on the internal `source_id` means deleting and re-adding the same app re-ingests everything as duplicates. Key on the upstream identity (app package plus review ID) instead.
5. **"Newer or equal" breaks when timestamps are missing or coarse.** Tweets have no update time, so you're comparing NULL to NULL. Two payloads stamped in the same second will flip-flop.
6. **Language is a required common attribute, and it will be mostly null.** Saying "nullable" means the requirement isn't met.
7. **The `kind` list mixes types and sources.** "tweet" is a source, not a feedback type.
8. **Schema evolution breaks reads.** Old metadata blobs will fail the new Pydantic models. Add a `metadata_version` field, or validate strictly on write and leniently on read.

### The First Principles Thinker (Response E)
**What's actually being solved:** the schema decides what one piece of feedback is and when two payloads are the same piece. Most of the cross-questioning will come back to that.

1. **`kind` mixes up source and shape.** A tweet is a source, not a kind of feedback. Use `review | conversation | post`, so Twitter maps to `post` and Discourse maps to `post`. If `tweet` stays in `kind`, the interviewer will say "so a new source means a new kind?" and the extensibility argument falls apart.
2. **Decide what one Intercom record is.** If the whole conversation is one row and you upsert it, every new reply overwrites the row. Pick one answer and say it out loud: one row per conversation, with the replies kept in `text` and `metadata`.
3. **Drop the sha256.** `UNIQUE(source_id, external_id)` does the same job. A composite key a non-author can explain in five seconds.
4. **You're merging two different problems.** Idempotency means the same event arriving twice; the unique key plus the upsert handles that. Dedupe means the same feedback showing up in two places, like a tweet cross-posted to the forum. That's content-level matching, and you're not doing it. Say so before they ask.
5. **Edits and deletes are the weakest point.** An edited tweet gets a new tweet ID; map it to the original tweet's ID. Add a nullable `deleted_at`. And replaying `raw_events` after a fix has to skip the timestamp check, or the corrected rows never get written.

Everything else, including JSON metadata typed by Pydantic and `source` as its own table, holds up as it is.

## 3. Anonymisation mapping

A = The Outsider, B = The Executor, C = The Expansionist, D = The Contrarian, E = The First Principles Thinker

## 4. Peer reviews

### Review by The Contrarian
1. Strongest: D. Only response testing the design against how sources behave: Intercom webhooks send only the new part so LWW upsert replaces whole conversation; edited tweet gets new ID so arrives as duplicate; delete+re-add source re-ingests everything; old metadata blobs fail newer Pydantic models. B second: only one spotting NULL >= NULL silently never updating.
2. Biggest blind spot: C. Praises instead of tests; adds enrichment/generated columns/transformer_version yet claims evolution breaks "nothing" (D #8 shows false); misses replay blocked by timestamp check (E #5), missing timestamps, partial webhooks.
3. All missed: replay brings deleted rows back unless delete events are in raw_events too; verbatim raw payloads vs GDPR erasure; tenant_id on records and on source can disagree (composite FK); nobody asked who verifies webhook signatures; pull cursor order (cursor advanced before commit loses data on crash; out-of-order delivery); duplicates pile up in raw_events unchecked.

### Review by The First Principles Thinker
1. Strongest: E. Names the real problem (what is one piece of feedback; when are two payloads the same). Separates idempotency from dedupe and admits cross-source dedupe isn't done. Catches replay must skip timestamp check. D close second (partial webhooks, Twitter edit IDs sharpest catches).
2. Biggest blind spot: C. Adds features for a candidate who must defend every line; never questions correctness; misses tweet-in-kind, NULL comparison, partial payloads.
3. All missed: the source system holds the truth; our table is a copy. Treat push as a trigger to re-fetch the full object and partial deltas, ordering and missing timestamps go away together. Nobody checked that webhook and poll for the same item produce the same external_id. Tenant isolation: denormalized tenant_id can disagree with source.tenant_id; nothing enforces tenant scoping on reads.

### Review by The Expansionist
1. Strongest: C. Treats design as something to build on: raw_events as truth with feedback_records as rebuildable view answers schema evolution in one sentence; transformer_version and parent_external_id each give capability for one column. D has most damaging catches but only removes risk.
2. Biggest blind spot: A. Treats every column as a liability; misses that replaying raw_events answers half the questions; misses partial-webhook problem.
3. All missed: D's partial-webhook fix is a design win: if every push is only a signal to fetch the full current record, push and pull become one code path and webhook payloads never need parsing. Stored raw payloads double as recorded fixtures for transformer contract tests and a live replay demo.

### Review by The Outsider
1. Strongest: E. Opens with what counts as one piece of feedback; splits idempotency from dedupe; replay must skip timestamp check. D finds the sharpest bug (partial Intercom webhook) but reads as a defect list.
2. Biggest blind spot: C. Adds features; claims nothing breaks on evolution (false per D #8); skips basics (missing timestamps, pointless sha256, tweet in kind).
3. All missed: walk one real payload through the whole system on the whiteboard first; how tenants are kept apart on reads and how a webhook is matched to tenant+source (per-source URL, signature); what happens when a transform fails (no error status, no retry); the D vs B/E conflict on one-row-per-conversation upsert was never resolved.

### Review by The Executor
1. Strongest: B. Finds what crashes or misbehaves Monday: `metadata` clashes with SQLAlchemy declarative Base; NULL source_updated_at in ON CONFLICT WHERE silently never updates; SQLite compares datetimes as strings and drops tz; SQLite has no SKIP LOCKED so transform could run inside the insert transaction; build order ends in a test.
2. Biggest blind spot: C. Every idea adds work; generated columns don't fit SQLite; misses partial Intercom webhooks and NULL-timestamp trap.
3. All missed: pull cursor and push routing. Cursor advanced in a separate commit from the upserts loses or duplicates a page on crash. Nobody says how a webhook is matched to source_id and tenant (URL path, signature, both) nor that webhook_secret must be checked before writing raw_events; getting this wrong lets one tenant's data land in another's records.

## 5. Chairman synthesis

### Verdict

The proposed design holds once six things change, and every change makes it smaller or safer:
1. drop the sha256 key for `UNIQUE(source_id, external_id)`;
2. take "tweet" out of `kind`;
3. add a `deleted_at` tombstone;
4. make the timestamp guard NULL-safe with `COALESCE`, and let replay skip it;
5. require every write to be a full snapshot, which settles the Intercom clash;
6. stop duplicate deliveries at `raw_events`.

The council's strongest inputs were these:
- the Contrarian's partial-webhook and Twitter-edit catches;
- the Executor's build traps (the reserved `metadata` name, NULL in the `ON CONFLICT ... WHERE` clause, SQLite storing datetimes as text);
- the First Principles split between idempotency and cross-source dedupe.

From the Expansionist, only `connector_version` was kept. Every peer review except the Expansionist's own named it the weakest response, because it added work without testing correctness.

Weighting:
- First Principles and Contrarian (correctness): high.
- Executor (buildability): high.
- Outsider (defensibility): medium. Used to cut columns and to word the interview answers.
- Expansionist (growth): low. One column adopted.

The full decision follows. It is identical to ADR-002 from its Context section onward.

### Context

Feedback comes from four sources. Each one sends a different shape.

| Source | How it arrives here | What one item looks like |
|---|---|---|
| Playstore | push, fed from fixture files | one review with a rating and an app version |
| Twitter | push, fed from fixture files | one tweet with a language and a country |
| Intercom | push, fed from fixture files | one conversation with many messages ("parts") |
| Discourse | pull, live from a real forum | one forum post inside a topic |

We must turn all of them into one standard record. That record needs:
- common fields: tenant, source, language, text, and so on;
- room for source-only fields, like Playstore's app version;
- a way to handle the same item arriving twice (idempotency);
- support for two sources of the same type for one tenant (two Playstore apps).

Some things were fixed before this review:
- one `feedback_records` table with typed common columns, plus one JSON `metadata` column;
- the JSON is checked by a Pydantic model per source;
- `Source` is its own table;
- every raw payload is kept in `raw_events`, which is also the work queue;
- SQLite through SQLAlchemy 2.0, Pydantic v2, `mypy --strict`.

This ADR settles everything else: the key, the kinds of feedback, deletes, timestamps, versions, and what one Intercom record is.

Jargon used below:
- **Idempotency**: processing the same input twice leaves the same result as processing it once.
- **Upsert**: insert a row, or update it if it already exists.
- **Tombstone**: a marker that says "this was deleted", kept instead of removing the row.
- **Snapshot**: the full current state of an item, not just what changed.
- **Replay**: re-running stored raw payloads through the transformer, usually after fixing a bug.

### Decision

#### The `feedback_records` table, column by column

| Column | Type | Why it exists |
|---|---|---|
| `id` | integer, primary key | Our own row id, so nothing depends on a source's id format. |
| `tenant_id` | FK, not null | Lets every read filter by customer without a join. It is always copied from `source.tenant_id`, never from the payload. |
| `source_id` | FK to `sources`, not null | Says which connection the item came from. Two Playstore apps are two source rows. |
| `source_type` | enum `playstore \| twitter \| intercom \| discourse` | Lets you filter by where feedback came from. It also picks which metadata model to use. |
| `external_id` | text, not null | The source's own id for the item: review id, original tweet id, conversation id, post id. |
| `kind` | enum `review \| conversation \| post` | The shape of the feedback, not where it came from. |
| `title` | text, nullable | Only some sources have a title, like a Discourse topic or an Intercom subject. |
| `text` | text, not null | The feedback itself. For Intercom, every message joined in order. |
| `author` | text, nullable | The name or handle as the source gives it. |
| `language` | text, nullable | Filled from the source when it sends one (Playstore, Twitter). We do not detect it. |
| `rating` | integer, nullable | Only reviews have a star rating. |
| `source_created_at` | datetime, not null | When the source says the item was created. Written once on insert and never changed. |
| `source_updated_at` | datetime, nullable | When the source says the item last changed. Many sources never send it. |
| `ingested_at` | datetime, not null | When we first stored the row. |
| `last_ingested_at` | datetime, not null | When we last wrote the row. |
| `deleted_at` | datetime, nullable | The tombstone. Set when the source tells us the item was deleted. |
| `connector_version` | text, not null | Which transformer built this row, like `playstore-v1`. Lets us replay only the rows a buggy version made. |
| `raw_event_id` | FK to `raw_events`, not null | The raw payload that last wrote this row, so any row can be traced back to its input. |
| `metadata` | JSON, not null | Source-only fields, checked by that source's Pydantic model. |

#### Uniqueness rule

- `UNIQUE(source_id, external_id)`. One item from one source is one row.
- There is no sha256 `dedupe_key`. A hash of the same fields gives the same guarantee and only adds something to explain.
- Tenants are kept apart through the source. A source row belongs to exactly one tenant. So the same external id in two tenants, or in two apps of one tenant, sits under two different `source_id`s and cannot collide.
- Sources are disabled, never hard-deleted. Re-adding the same app turns the old source row back on, so its records do not come in again as duplicates.

#### Tenant column safety

- `tenant_id` is copied onto records so reads stay simple. It is always written from `source.tenant_id`.
- The database enforces this. `sources` has `UNIQUE(id, tenant_id)`, and records have a composite foreign key `(source_id, tenant_id) -> sources(id, tenant_id)`. A record whose tenant does not match its source cannot be written. (SQLite needs `PRAGMA foreign_keys=ON`.)

#### Kind enum

- `review | conversation | post`.
- Playstore maps to `review`. Intercom maps to `conversation`. Twitter and Discourse both map to `post`.
- "tweet" is a source, not a kind. A new source should reuse a kind, not add one.

#### Update rule (the upsert)

There is one statement, an `INSERT ... ON CONFLICT (source_id, external_id) DO UPDATE ... WHERE`:

```sql
WHERE COALESCE(excluded.source_updated_at, excluded.source_created_at)
   >= COALESCE(feedback_records.source_updated_at, feedback_records.source_created_at)
```

- In plain words: compare "when did this version last change" on both sides. If the source sends no update time, use the creation time instead.
- What a NULL does: a NULL `source_updated_at` falls back to `source_created_at`. That column is never NULL, so the comparison is never NULL. Without `COALESCE`, `NULL >= x` is NULL, and SQLite would silently never update.
- An older snapshot loses and is ignored. That is how out-of-order delivery is handled.
- On a tie, the later arrival wins. A re-sent identical version rewrites identical values, which is harmless. Duplicate deliveries are already stopped in `raw_events`, so two versions cannot keep flipping back and forth.
- The update never touches `source_created_at`, `ingested_at` or `deleted_at`.

#### Replay

- Replay uses the same upsert without the `WHERE`. It bypasses the timestamp guard on purpose.
- Why: after a transformer fix, the stored row has the same timestamp as the payload. With the guard on, the corrected row would never be written.
- Replay processes raw events in `raw_events.id` order. Delete events are raw events too, so tombstones are applied again and deleted items do not come back.

#### Deletes

- A delete payload sets `deleted_at = COALESCE(deleted_at, <delete time>)`. Rows are never hard-deleted.
- Normal upserts never clear `deleted_at`. Once deleted, an item stays deleted.
- Reads hide tombstoned rows by default.
- Known gap: a delete for an id we have never seen writes nothing and is logged. Discourse pull cannot see deletes at all, because search does not return deleted posts.

#### Timestamps

- Store naive UTC everywhere. "Naive" means no timezone attached.
- Each transformer converts source times to UTC and then drops the timezone.
- Why: SQLite has no datetime type. It stores and compares datetimes as text, and it loses timezone offsets. If every value is naive UTC, text order matches time order.

#### Metadata in code

- In SQLAlchemy the column is called `metadata`, but the Python attribute is `source_metadata`. SQLAlchemy's declarative `Base` already uses the name `.metadata`, and reusing it crashes at import:
  `source_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)`.
- Write it with `model.model_dump(mode="json")`. This turns datetimes and enums into plain JSON values.
- Each metadata model has a `source_type: Literal["playstore"]` (and so on) field. Together they form a discriminated union: `Annotated[PlaystoreMetadata | TwitterMetadata | IntercomMetadata | DiscourseMetadata, Field(discriminator="source_type")]`. Pydantic and mypy then always know which model a blob is.
- Strict on write: the transformer builds the model from the payload, so wrong types fail before any database write.
- Lenient on read: models use `extra="ignore"`, and every new field must have a default. Old blobs still load. Renaming or removing a field means bumping `connector_version` and replaying.

#### What one record is, per source, and the partial-payload rule

General rule: every write must be a full snapshot of the item.
- If a push payload is not a full snapshot and the source has an API we can read, the push is only a trigger. We fetch the full object and upsert that.
- If the source has no API we can read, the connector must build the full snapshot itself before writing.

| Source | One record is | Which rule applies here |
|---|---|---|
| Playstore (push, fixtures) | one review | Each payload is a full review, so it is upserted as is. |
| Twitter (push, fixtures) | one tweet, keyed by the original tweet id | Each payload is a full tweet, so it is upserted as is. An edited tweet gets a new id, so `external_id = edit_history_tweet_ids[0]` (the original). The newest tweet id goes in metadata. A delete event writes a tombstone. |
| Intercom (push, fixtures) | one conversation; its messages live in `metadata.parts` and are joined into `text` | There is no live API here, so the connector builds the snapshot. It merges the incoming parts into the stored parts by part id, sorts them by time, and rebuilds `text`. The same part arriving twice is still one part. A full snapshot merges cleanly too, so there is one code path. Against the real Intercom API, this becomes "fetch the conversation". |
| Discourse (pull, live) | one post | Pull already fetches full posts, so they are upserted as is. If Discourse webhooks are added later, they are triggers to fetch. |

#### `raw_events` duplicates

- `UNIQUE(source_id, delivery_key)`. `delivery_key` is the source's own event id when it sends one. Otherwise it is the sha256 of the payload as canonical JSON (`json.dumps(sort_keys=True)`).
- Inserts use `ON CONFLICT DO NOTHING`, and the caller still gets `202`. A duplicate webhook is stored once and processed once.
- This is the only hash in the design. It exists because a delivery has no natural id, while a feedback item always has one.
- The webhook URL carries the source id. Its signature is checked against `source.webhook_secret` before anything is written to `raw_events`.
- The pull cursor moves forward only after the raw rows are committed. The overlap window then re-sends a few items, and the rule above absorbs them.

#### Scope

- **In scope (idempotency):** the same item, or the same delivery, arriving twice gives one row.
- **Out of scope (cross-source dedupe):** the same complaint posted on Twitter and on Discourse stays two records. Matching them needs content similarity. That is an analysis feature, not an ingestion one.

### Where the council agrees

- Drop the sha256 key and use `UNIQUE(source_id, external_id)` (Outsider, Executor, Contrarian, First Principles). The tenant is already implied by the source.
- Take "tweet" out of `kind`; use `review | conversation | post` (Outsider, Contrarian, First Principles).
- Add a nullable `deleted_at` tombstone (all five).
- NULL `source_updated_at` needs a stated rule (Outsider, Executor, Contrarian). The Executor gave the fix: `COALESCE` with the creation time.
- One table plus Pydantic-checked JSON, with `Source` as its own entity, holds up (all five).
- Language will be mostly empty, and that has to be said out loud (Outsider, Contrarian, Expansionist).

### Where the council clashes

1. **Intercom: one row per conversation, or does it break?** The Executor and First Principles said one row, with parts in metadata. The Contrarian said a partial reply webhook would overwrite the whole thread. **Ruling: one row per conversation, plus the full-snapshot rule.** The connector merges parts by part id, so a partial payload can never shrink the record. Both sides are right, and the rule makes them agree.
2. **Key on our `source_id` or on the upstream identity (app package plus review id)?** The Contrarian warned that deleting and re-adding a source re-ingests everything as duplicates. **Ruling: keep `source_id`.** Sources are disabled, never deleted, and re-adding one turns the old row back on. An upstream key would need a different key format for every source.
3. **Grow the design (Expansionist) or keep it small (Outsider, Executor)?** **Ruling: take one column, cut the rest.** `connector_version` is kept, because it makes "replay only what v1 built" possible. `parent_external_id`, Postgres generated columns and an enrichment stage are cut. They are not needed, they do not fit SQLite, and each one is another thing to defend.
4. **Is nullable language a missed requirement (Contrarian) or a deliberate gap (Outsider)?** **Ruling: deliberate gap.** The column exists and is filled whenever the source gives a language. Detection would be a later step that writes the same column, and nothing about the schema changes.
5. **Tie-break: `>=` or `>`?** The Contrarian warned that same-second payloads flip-flop. **Ruling: `>=`.** Duplicate deliveries never reach the upsert, because `raw_events` stops them. A tie therefore means two real versions, and the later arrival is the better guess.
6. **Does schema evolution break "nothing" (Expansionist) or break reads (Contrarian)?** **Ruling: the Contrarian is right.** The fix is lenient reads, defaults on every new field, and a version bump plus replay for breaking changes.

### Blind spots the council caught

These came out of the peer reviews. No single response had them.

- **Replay could bring deleted rows back.** Fixed: deletes are raw events, replay runs in order, and upserts never clear `deleted_at`.
- **`tenant_id` on a record could disagree with its source.** Fixed: a composite foreign key enforces it.
- **Duplicate webhooks pile up in `raw_events`.** Fixed: `UNIQUE(source_id, delivery_key)`.
- **Webhook routing and signatures.** Fixed: the source id is in the URL, and the HMAC signature is checked before any write. Otherwise one tenant's data could land in another's records.
- **Pull cursor and crashes.** Fixed: the cursor moves only after the raw rows are committed. The overlap window plus the uniqueness rule absorb the repeats.
- **Failed transforms.** Already covered: `raw_events.status` and the error column in the existing plan. A failed event stays stored and can be replayed.
- **Webhook and poll must produce the same `external_id` for the same item.** Action: a contract test per connector.
- **Raw payloads versus GDPR erasure.** Out of scope, named. A real erasure request must hard-delete `raw_events` too, because a tombstone is not enough there.
- **Walk one real payload through the whole system first.** Raw payloads double as test fixtures and as the live replay demo.

### Rejected alternatives and why

| Alternative | Why not |
|---|---|
| Table per source type | Every cross-source query becomes a `UNION`, and a new source needs a migration. One table plus JSON gives both typed common columns and room for extras. |
| EAV (one row per attribute in a key-value table) | Loses types. Simple reads turn into pivots. Pydantic plus JSON already gives typed extras. |
| Content-hash dedupe | An edit changes the hash, so an edited review becomes a second record. Two different people writing "app crashes" would merge. The source's id is the real identity. |
| Append-only versioned records | Every query needs "latest version per item" logic. History is already in `raw_events`, so we keep one current row and rebuild from raw when needed. |
| Built-in language detection | It is a model choice with its own accuracy problems, and it is not ingestion. The nullable column leaves room for a later enrichment step. |
| Separate `conversations` parent table | It is a second entity that only Intercom uses. Parts in metadata plus the merge-by-part-id rule cover it. |
| sha256 `dedupe_key` | It gives the same guarantee as `UNIQUE(source_id, external_id)`, but nobody can read it. Tenant scoping already comes from the source. |

### How to say it in the interview

- **"What is one record?"** One piece of feedback as the source sees it. A Playstore review, a tweet (keyed by its original id), a Discourse post, or a whole Intercom conversation with its messages inside.
- **"Why no hash?"** `UNIQUE(source_id, external_id)` already means "this item from this source once". A hash of those same fields adds nothing except a question.
- **"Source edits a post."** It arrives with a newer update time, and the upsert overwrites the row. An older copy arriving late loses the timestamp check. An edited tweet has a new id, so we map it back to the original tweet's id.
- **"Source deletes a post."** We set `deleted_at` and hide the row from reads. We never remove it, and a replay applies the delete again because the delete is a stored raw event too.
- **"External ids collide across two apps."** They can't. Each app is its own source row, and the key includes `source_id`. Two tenants are likewise two different sources.
- **"Query across sources."** It's one table. Filter on `tenant_id`, `kind`, `language` or dates for everything. Reach into `metadata` only for source-specific fields.
- **"New source with weird metadata."** Write one transformer and one Pydantic metadata model, then add one registry entry. Pick an existing kind. No migration is needed.
- **"Schema evolves."** New metadata fields get defaults, so old rows still load. For a breaking change, bump `connector_version`, fix the transformer, and replay the stored raw payloads.
- **"Language is mostly null."** Yes, on purpose. We store it when the source sends it and don't guess. Detection would be a later step that fills the same column.

### The one thing to do first

Write one upsert test for the Playstore connector, before any other connector exists. It covers six steps:
1. ingest a review;
2. ingest the same delivery again, and check it still gives one raw event and one row;
3. send an edit with a newer time, and check the row is updated;
4. send an older copy, and check it is ignored;
5. send a payload with a NULL update time, and check the creation-time fallback;
6. replay after changing the transformer, and check the row is rewritten. Then send a delete and replay, and check the row stays deleted.

Every rule in this ADR is checked by that one test. The other three connectors copy the pattern.
