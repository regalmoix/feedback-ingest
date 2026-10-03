# ADR-002: Uniform feedback record and idempotency

## Status
Accepted (council-reviewed, 2026-10-03)

## Context

Feedback comes from four sources. Each one sends a different shape. (A fifth, `custom`, was added after this review; its row is at the end of the table.)

| Source | How it arrives here | What one item looks like |
|---|---|---|
| Playstore | push, fed from fixture files | one review with a rating and an app version |
| Twitter | push, fed from fixture files | one tweet with a language and a country |
| Intercom | push, fed from fixture files | one conversation with many messages ("parts") |
| Discourse | pull, live from a real forum | one forum post inside a topic |
| Custom (added later) | push, Enterpret's public webhook shape | a batch of records; each has its own `id`, `type` and `createdAt` |

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

## Decision

### The `feedback_records` table, column by column

| Column | Type | Why it exists |
|---|---|---|
| `id` | text (32 hex characters), primary key | A uuid5 of the source id and the external id. The same item always gets the same id, and nothing depends on a source's id format. |
| `tenant_id` | FK, not null | Lets every read filter by customer without a join. It is always copied from `source.tenant_id`, never from the payload. |
| `source_id` | FK to `sources`, not null | Says which connection the item came from. Two Playstore apps are two source rows. |
| `source_type` | enum `playstore \| twitter \| intercom \| discourse \| custom` | Lets you filter by where feedback came from. It also picks which metadata model to use. |
| `external_id` | text, not null | The source's own id for the item: review id, original tweet id, conversation id, post id, or the custom record's `id`. |
| `kind` | enum `review \| conversation \| post \| survey` | The shape of the feedback, not where it came from. Derived from `source_type` (for `custom`, from each record's `type`). `survey` was added with the custom connector. |
| `title` | text, nullable | Only some sources have a title, like a Discourse topic or an Intercom subject. |
| `text` | text, not null | The feedback itself. For Intercom, every message joined in order. |
| `author` | text, nullable | The name or handle as the source gives it. |
| `language` | text, nullable | Filled from the source when it sends one (Playstore, Twitter). We do not detect it. |
| `rating` | integer, nullable | Only reviews have a star rating. |
| `source_created_at` | datetime, not null | When the source says the item was created. Written once on insert and never changed. |
| `source_updated_at` | datetime, nullable | When the source says the item last changed. Many sources never send it. |
| `ingested_at` | datetime, not null | When we first stored the row. |
| `deleted_at` | datetime, nullable | The tombstone. Set when the source tells us the item was deleted. |
| `connector_version` | integer, not null | Which transformer version built this row, like `1`. Lets us replay only the rows a buggy version made. |
| `metadata` | JSON, not null | Source-only fields, checked by that source's Pydantic model. |

There is no `raw_event_id` column: every input payload stays in `raw_events` under its `source_id`, which is where a record is traced back to its inputs.

### Uniqueness rule

- `UNIQUE(source_id, external_id)`. One item from one source is one row.
- There is no sha256 `dedupe_key`. A hash of the same fields gives the same guarantee and only adds something to explain.
- Tenants are kept apart through the source. A source row belongs to exactly one tenant. So the same external id in two tenants, or in two apps of one tenant, sits under two different `source_id`s and cannot collide.
- Sources are disabled, never hard-deleted. To turn one back on, `PATCH /v1/sources/{id}` with `enabled: true`. A new `POST /v1/sources` is a new source with a new id, so its items ingest again as new records.

### Tenant column safety

- `tenant_id` is copied onto records so reads stay simple. It is always written from `source.tenant_id`.
- The database enforces this. `sources` has `UNIQUE(id, tenant_id)`, and records have a composite foreign key `(source_id, tenant_id) -> sources(id, tenant_id)`. A record whose tenant does not match its source cannot be written. (SQLite needs `PRAGMA foreign_keys=ON`.)

### Kind enum

- `review | conversation | post | survey`.
- Playstore maps to `review`. Intercom maps to `conversation`. Twitter and Discourse both map to `post` (the `KIND_BY_SOURCE` dict).
- "tweet" is a source, not a kind. A new source should reuse a kind, not add one.
- Added later: the `custom` connector is the one exception. Each custom record carries its own kind, taken from its `type` (`KIND_BY_RECORD_TYPE`): `REVIEW` is review, `CONVERSATION` is conversation, `FORUM_CONVERSATION_THREAD` is post, and `SURVEY` is the new `survey` kind.

### Update rule (the upsert)

The adapter reads the existing row and then inserts or updates, inside one `BEGIN IMMEDIATE` transaction so no other writer can interleave. The rule is the COALESCE rule below, applied in Python today (`merge(existing, incoming)` in `domain/models.py`, which both feedback stores call) inside `BEGIN IMMEDIATE`; the SQL `ON CONFLICT … WHERE` form shown here is the Postgres upgrade (extensions recipe 2, and a `ponytail:` comment in `feedback_store.py`). The rule:

```sql
WHERE COALESCE(excluded.source_updated_at, excluded.source_created_at)
   >= COALESCE(feedback_records.source_updated_at, feedback_records.source_created_at)
```

- In plain words: compare "when did this version last change" on both sides. If the source sends no update time, use the creation time instead.
- What a NULL does: a NULL `source_updated_at` falls back to `source_created_at`. That column is never NULL, so the comparison is never NULL. Without `COALESCE`, `NULL >= x` is NULL, and SQLite would silently never update.
- An older snapshot loses and is ignored. That is how out-of-order delivery is handled. One exception: an older delete still sets `deleted_at` if the row is not yet deleted.
- On a tie, the later arrival wins. A re-sent identical version rewrites identical values, which is harmless. Duplicate deliveries are already stopped in `raw_events`, so two versions cannot keep flipping back and forth.
- The update keeps `id`, `source_created_at` and `ingested_at`. It never clears `deleted_at`; an incoming delete can set it. It stores `source_updated_at` as the incoming version.
- No row yet: insert. This includes a delete for an id we have never seen, which inserts a tombstoned row.

### Replay

- Replay re-processes the stored raw event through the same upsert. An equal version is accepted by the upsert (`>=`), so a fixed connector's output overwrites the record.
- Why this is enough: after a transformer fix, the stored row has the same timestamp as the payload, and the tie goes to the later write.
- Replay order does not matter. An older version is skipped by the same guard, and deletes are sticky. Delete events are raw events too, so tombstones are applied again and deleted items do not come back.
- Both single replay (`POST /admin/raw-events/{id}/replay`) and bulk replay (`POST /admin/raw-events/replay?source_id=&status=&limit=`) exist.

### Deletes

- A delete payload sets `deleted_at = COALESCE(deleted_at, <delete time>)`. Rows are never hard-deleted.
- Normal upserts never clear `deleted_at`. Once deleted, an item stays deleted.
- Reads hide tombstoned rows by default.
- A delete for an id we have never seen inserts a tombstoned row: hidden from reads, and no later copy brings it back, because `deleted_at` is sticky. Known gap: Discourse pull cannot see deletes at all, because search does not return deleted posts.

### Timestamps

- Store naive UTC everywhere. "Naive" means no timezone attached.
- Each transformer converts source times to UTC and then drops the timezone.
- Why: SQLite has no datetime type. It stores and compares datetimes as text, and it loses timezone offsets. If every value is naive UTC, text order matches time order.

### Metadata in code

- In SQLAlchemy the column is called `metadata`, but the Python attribute is `source_metadata`. SQLAlchemy's declarative `Base` already uses the name `.metadata`, and reusing it crashes at import:
  `source_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)`.
- Write it with `model.model_dump(mode="json")`. This turns datetimes and enums into plain JSON values.
- Each metadata model has a `source_type: Literal["playstore"]` (and so on) field. Together they form a discriminated union: `Annotated[DiscourseMetadata | PlaystoreMetadata | TwitterMetadata | IntercomMetadata | CustomMetadata, Field(discriminator="source_type")]`. Pydantic and mypy then always know which model a blob is.
- Strict on write: the transformer builds the model from the payload, so wrong types fail before any database write.
- Lenient on read: models ignore unknown keys (Pydantic's default), and every new field must have a default. Old blobs still load. Renaming or removing a field means bumping `connector_version` and replaying.

### What one record is, per source, and the partial-payload rule

General rule: every write must be a full snapshot of the item.
- If a push payload is not a full snapshot and the source has an API we can read, the push is only a trigger. We fetch the full object and upsert that.
- If the source has no API we can read, the connector must build the full snapshot itself before writing.

| Source | One record is | Which rule applies here |
|---|---|---|
| Playstore (push, fixtures) | one review | Each payload is a full review, so it is upserted as is. A review with no user comment goes dead ("review has no user comment"), so a bad payload never looks like "no data". |
| Twitter (push, fixtures) | one tweet, keyed by the original tweet id | Each payload is a full tweet, so it is upserted as is. An edited tweet gets a new id, so `external_id = edit_history_tweet_ids[0]` (the original). Edits stay keyed to the original id; the raw event keeps the newest tweet id, so metadata has no `latest_tweet_id`. Delete events: known gap; fixtures carry no delete shape; a `TweetDeleteIn` branch is the extension. |
| Intercom (push, fixtures) | one conversation; its messages are joined into `text`, and metadata keeps `part_count`, `tags` and `state` | Intercom's conversation webhooks carry the whole conversation object including `conversation_parts`, so every push is already a full snapshot and the normal upsert applies. No merge step is needed. If a future source sends deltas, its connector must fetch the full object before transforming (the snapshot rule). Only `conversation.*` topics are transformed, from the full item. `ping` gives no records. Any other topic, for example `conversation_part.redacted`, goes dead as "unsupported topic". `conversation.deleted` is not special-cased: it goes dead on validation if its item is not a full conversation, and upserts if it is. A real delete path is a known gap. |
| Discourse (pull, live) | one post | Pull already fetches full posts, so they are upserted as is. If Discourse webhooks are added later, they are triggers to fetch. Pull mode never delivers deletions, because search excludes deleted posts. Webhooks are push-only (ADR-003 ruling 8), so a Discourse delete would need a push source. |
| Custom (push, added later) | one record per entry in the batch | Each entry is a full record. Its `id` becomes `external_id`, and it upserts on `(source_id, external_id)` with the version guard. One push is one raw event, keyed by the hash of the whole batch. An unsupported `type` sends the whole batch dead. |

### `raw_events` duplicates

- `UNIQUE(source_id, external_event_id)`. `external_event_id` is the item id plus its last-changed time, for example `"{post id}:{updated_at}"` (Intercom adds a short hash of the item). When the payload does not validate, or for a custom batch, it is the sha256 of the payload as canonical JSON (`json.dumps(sort_keys=True)`).
- A duplicate `(source_id, external_event_id)` is detected inside the same write transaction and the insert is skipped; the caller still gets `202` with `duplicate: true`. A duplicate webhook is stored once and processed once. A duplicate of a dead row is left dead: a WARNING says to replay it.
- This key is the only place dedupe uses a payload hash. It exists because a delivery has no natural id, while a feedback item always has one.
- The webhook URL carries the source id. Its signature is checked against `source.webhook_secret` before anything is written to `raw_events`. Only push sources accept webhooks.
- The pull cursor moves forward only after the raw rows are committed. The overlap window then re-sends a few items, and the rule above absorbs them.

### Scope

- **In scope (idempotency):** the same item, or the same delivery, arriving twice gives one row.
- **Out of scope (cross-source dedupe):** the same complaint posted on Twitter and on Discourse stays two records. Matching them needs content similarity. That is an analysis feature, not an ingestion one.

## Where the council agrees

- Drop the sha256 key and use `UNIQUE(source_id, external_id)` (Outsider, Executor, Contrarian, First Principles). The tenant is already implied by the source.
- Take "tweet" out of `kind`; use `review | conversation | post` (Outsider, Contrarian, First Principles).
- Add a nullable `deleted_at` tombstone (all five).
- NULL `source_updated_at` needs a stated rule (Outsider, Executor, Contrarian). The Executor gave the fix: `COALESCE` with the creation time.
- One table plus Pydantic-checked JSON, with `Source` as its own entity, holds up (all five).
- Language will be mostly empty, and that has to be said out loud (Outsider, Contrarian, Expansionist).

## Where the council clashes

1. **Intercom: one row per conversation, or does it break?** The Executor and First Principles said one row, with parts in metadata. The Contrarian said a partial reply webhook would overwrite the whole thread. **Ruling: one row per conversation, plus the full-snapshot rule.** Intercom's real webhooks send the full conversation with all parts, so the fixtures mirror that and no merge is needed. The rule stays: a connector may only write a full snapshot; a delta-only source must fetch first. (Chairman originally proposed a merge-by-part-id step; the advisor review removed it as unnecessary for Intercom's actual payloads.)
2. **Key on our `source_id` or on the upstream identity (app package plus review id)?** The Contrarian warned that deleting and re-adding a source re-ingests everything as duplicates. **Ruling: keep `source_id`.** Sources are disabled, never deleted. Built: re-enable a source with PATCH; a new POST is a new source and ingests again. An upstream key would need a different key format for every source.
3. **Grow the design (Expansionist) or keep it small (Outsider, Executor)?** **Ruling: take one column, cut the rest.** `connector_version` is kept, because it makes "replay only what v1 built" possible. `parent_external_id`, Postgres generated columns and an enrichment stage are cut. They are not needed, they do not fit SQLite, and each one is another thing to defend.
4. **Is nullable language a missed requirement (Contrarian) or a deliberate gap (Outsider)?** **Ruling: deliberate gap.** The column exists and is filled whenever the source gives a language. Detection would be a later step that writes the same column, and nothing about the schema changes.
5. **Tie-break: `>=` or `>`?** The Contrarian warned that same-second payloads flip-flop. **Ruling: `>=`.** Duplicate deliveries never reach the upsert, because `raw_events` stops them. A tie therefore means two real versions, and the later arrival is the better guess.
6. **Does schema evolution break "nothing" (Expansionist) or break reads (Contrarian)?** **Ruling: the Contrarian is right.** The fix is lenient reads, defaults on every new field, and a version bump plus replay for breaking changes.

## Blind spots the council caught

These came out of the peer reviews. No single response had them.

- **Replay could bring deleted rows back.** Fixed: deletes are raw events, and upserts never clear `deleted_at`, so replay order does not matter.
- **`tenant_id` on a record could disagree with its source.** Fixed: a composite foreign key enforces it.
- **Duplicate webhooks pile up in `raw_events`.** Fixed: `UNIQUE(source_id, external_event_id)`.
- **Webhook routing and signatures.** Fixed: the source id is in the URL, and the HMAC signature is checked before any write. Otherwise one tenant's data could land in another's records.
- **Pull cursor and crashes.** Fixed: the cursor moves only after the raw rows are committed. The overlap window plus the uniqueness rule absorb the repeats.
- **Failed transforms.** Already covered: `raw_events.status` and the error column in the existing plan. A failed event stays stored and can be replayed.
- **Webhook and poll must produce the same `external_id` for the same item.** Superseded: webhooks are push-only (ADR-003 ruling 8), so one source never receives both. No such test exists.
- **Raw payloads versus GDPR erasure.** Out of scope, named. A real erasure request must hard-delete `raw_events` too, because a tombstone is not enough there.
- **Walk one real payload through the whole system first.** Raw payloads double as test fixtures and as the live replay demo.

## Rejected alternatives and why

| Alternative | Why not |
|---|---|
| Table per source type | Every cross-source query becomes a `UNION`, and a new source needs a migration. One table plus JSON gives both typed common columns and room for extras. |
| EAV (one row per attribute in a key-value table) | Loses types. Simple reads turn into pivots. Pydantic plus JSON already gives typed extras. |
| Content-hash dedupe | An edit changes the hash, so an edited review becomes a second record. Two different people writing "app crashes" would merge. The source's id is the real identity. |
| Append-only versioned records | Every query needs "latest version per item" logic. History is already in `raw_events`, so we keep one current row and rebuild from raw when needed. |
| Built-in language detection | It is a model choice with its own accuracy problems, and it is not ingestion. The nullable column leaves room for a later enrichment step. |
| Separate `conversations` parent table | It is a second entity that only Intercom uses. Parts in metadata plus the full-snapshot rule cover it. |
| sha256 `dedupe_key` | It gives the same guarantee as `UNIQUE(source_id, external_id)`, but nobody can read it. Tenant scoping already comes from the source. |

## How to say it in the interview

- **"What is one record?"** One piece of feedback as the source sees it. A Playstore review, a tweet (keyed by its original id), a Discourse post, or a whole Intercom conversation with its messages inside.
- **"Why no hash?"** `UNIQUE(source_id, external_id)` already means "this item from this source once". A hash of those same fields adds nothing except a question.
- **"Source edits a post."** It arrives with a newer update time, and the upsert overwrites the row. An older copy arriving late loses the timestamp check. An edited tweet has a new id, so we map it back to the original tweet's id.
- **"Source deletes a post."** We set `deleted_at` and hide the row from reads. We never remove it, and a replay applies the delete again because the delete is a stored raw event too. A delete for an item we never saw still writes a hidden tombstone row.
- **"External ids collide across two apps."** They can't. Each app is its own source row, and the key includes `source_id`. Two tenants are likewise two different sources.
- **"Query across sources."** It's one table. Filter on `tenant_id`, `kind`, `language` or dates for everything. Reach into `metadata` only for source-specific fields.
- **"New source with weird metadata."** Add the `SourceType` value, one Pydantic metadata model, one connector file, one registry entry and fixtures (ADR-003 has the recipe). Pick an existing kind. No migration is needed. The custom connector was added this way; it also added the `survey` kind, which was one enum value.
- **"Schema evolves."** New metadata fields get defaults, so old rows still load. For a breaking change, bump `connector_version`, fix the transformer, and replay the stored raw payloads.
- **"Language is mostly null."** Yes, on purpose. We store it when the source sends it and don't guess. Detection would be a later step that fills the same column.

## The one thing to do first

Write one upsert test for the Playstore connector, before any other connector exists. It covers six steps:
1. ingest a review;
2. ingest the same delivery again, and check it still gives one raw event and one row;
3. send an edit with a newer time, and check the row is updated;
4. send an older copy, and check it is ignored;
5. send a payload with a NULL update time, and check the creation-time fallback;
6. replay after changing the transformer, and check the row is rewritten. Then send a delete and replay, and check the row stays deleted.

Every rule in this ADR is checked by that one test. The other three connectors copy the pattern.
