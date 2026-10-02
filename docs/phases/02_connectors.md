# Phase 2 — Connectors and transform

Status: implemented and review-fixed 2026-10-03 (commits 6264b45, d8648f1). Depends on Phase 1 and ADR-003 (ADR-003 is authoritative where they differ). Still no HTTP endpoints.

## What this phase builds, in one paragraph

The translation layer. A connector is the code for one source type (Discourse, Playstore, Twitter, Intercom)
that turns one raw payload into zero or more uniform `FeedbackRecord`s. Every connector first validates the
payload with a small Pydantic "input model" so a malformed payload fails loudly at one line, then maps fields
into the record and the source-specific metadata model. A registry dict maps each `SourceType` to its
connector, so no other code ever branches on source type. Discourse also knows how to pull: it returns pages
of payloads with a cursor per page. A shared contract test runs every connector over every fixture file, so a
new source is "one file, one metadata model, one registry entry, one fixture, and the contract test passes".

## Glossary for this phase

- Connector: a class for one source type. Not a Source row. "A Source is a tenant's configured instance; a
  connector is the code that translates for one source type."
- Input model: a Pydantic model describing the payload the source actually sends. Validation happens here.
- Contract test: one test file parametrised over every connector and every fixture; the rules every connector
  must obey.
- Tombstone: a record emitted with `deleted_at` set, meaning "the source deleted this".

## Connector contract (`feedback_ingest/connectors/base.py`)

```python
class PullPage(BaseModel):
    payloads: list[dict[str, Any]]
    cursor: str                     # cursor to store once this page's raw rows are committed

class SourceConnector(Protocol):
    source_type: ClassVar[SourceType]
    version: ClassVar[int]          # bump when transform output changes; stamped on every record
    required_config: ClassVar[tuple[str, ...]]  # config keys check_source demands of a pull source
    def external_event_id(self, payload: Mapping[str, Any]) -> str: ...
    def transform(self, source: Source, payload: Mapping[str, Any]) -> list[FeedbackRecord]: ...
    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool: ...

class PullConnector(SourceConnector, Protocol):
    def pull(self, source: Source, http: HttpClient, now: datetime) -> Iterator[PullPage]: ...

def default_verify_signature(secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
    # HMAC-SHA256 hex of the raw body, header "X-Signature"; uses utils.signing.verify

def record_id(source_id: str, external_id: str) -> str:
    # uuid5(NAMESPACE_URL, f"{source_id}:{external_id}").hex: the same item always gets the same id
```
Rules every connector obeys (these are the contract test):
- `external_event_id` is `f"{item id}:{updated-or-created timestamp}"` when the payload has them, else
  `utils.hashing.payload_hash(payload)`. Discourse uses `deleted_at or updated_at or created_at` as the
  timestamp; Intercom appends a short hash of the conversation item. Reason: a bare item id would make a re-pulled *edited* post collide on
  the raw_events unique key and be silently dropped, so the record would never update.
- `transform` returns a list: empty for payloads that are not feedback (ping, bot message), one record normally,
  several when one payload holds several items, and a record with `deleted_at` set for a deletion.
- `transform` lets Pydantic's `ValidationError` propagate for malformed payloads and raises `TransformError` for
  any other permanent problem; the worker (Phase 3) catches both in one `except` and marks the event dead. It
  never raises anything else on bad data.
- `transform` is deterministic: same input, same output. Connectors are clock-free: `ingested_at` is a required
  field, so connectors set it from `source_created_at` as a placeholder and the pipeline (Phase 3) overwrites it
  with the real clock before upsert. `id` is `record_id(source.id, external_id)`, a `uuid5`, so it is deterministic
  too and the determinism check compares whole records.
- Each record has `source_type == connector.source_type`, `metadata.source_type == connector.source_type`,
  `tenant_id/source_id` copied from the `Source`, `connector_version == connector.version`.
- Every connector's `verify_signature` is a two-line method delegating to `default_verify_signature` unless the real source signs
  differently (none of the four in this project override; the hook is where Intercom's SHA1 `X-Hub-Signature`
  or Discourse's `X-Discourse-Event-Signature: sha256=` would go).

## Registry (`feedback_ingest/connectors/registry.py`)
```python
_ALL: tuple[SourceConnector, ...] = (DiscourseConnector(), PlaystoreConnector(), TwitterConnector(), IntercomConnector())
CONNECTORS: dict[SourceType, SourceConnector] = {c.source_type: c for c in _ALL}
_PULL: tuple[PullConnector, ...] = (DiscourseConnector(),)
PULLERS: dict[SourceType, PullConnector] = {c.source_type: c for c in _PULL}
def check_source(source: Source) -> None  # ValueError: pull mode without a puller, or bad pull config
```
Callers index the dicts directly: `CONNECTORS[source.type]`, `PULLERS[source.type]`. `check_source` is meant to run at
Source creation (wired into the create endpoint in Phase 5) and also checks the puller's `required_config` keys (Discourse: `base_url`, `start_after`)
and that `start_after` parses as a datetime.
No `runtime_checkable`/`isinstance`: the pull-capable instances are listed explicitly, which keeps mypy honest.
Tests assert `set(SourceType) == set(CONNECTORS)` and `set(PULLERS) <= set(CONNECTORS)`.

## The four connectors (one file each, ≤120 lines, input model at the top of the file)

Payloads are synthetic but shaped like the real APIs. Every fixture under `tests/fixtures/<source_type>/*.json`
is invented data (no real names, handles, emails, or ids).

### Discourse (`connectors/discourse.py`) — pull + push, `kind=post`
- Input model `DiscoursePostIn`: `id: int, topic_id: int, post_number: int, username: str, name: str | None,
  created_at: datetime, updated_at: datetime | None, cooked: str, topic_slug: str, topic_title: str | None,
  deleted_at: datetime | None`, `like_count: int = 0`. `cooked` is HTML; `text` is the stripped text via
  `utils/html.strip_tags` (stdlib `html.parser`). The datetime fields are `NaiveUtc`.
- `external_id = str(id)`; `external_event_id = f"{id}:{(deleted_at or updated_at or created_at).isoformat()}"`,
  so a deletion is a new raw event even when `updated_at` did not change.
- `metadata = DiscourseMetadata(topic_id, post_number, like_count, url)` where
  `url = f"{source.config['base_url']}/t/{topic_slug}/{topic_id}/{post_number}"`.
- `title = topic_title`, `author = name or username`, `language = None`, `rating = None`.
- `deleted_at` present → record with `deleted_at` set (tombstone fixture: `discourse/post_deleted.json`).
- `pull(source, http, now)` lives in `connectors/discourse_pull.py` (`pull_pages`); the connector delegates to it.
  - `since = source.cursor or config["start_after"]`, parsed as `NaiveUtc` (unparseable → `TransformError`).
    The window is bounded: `until = min(now + 1 day, since + window_days)`, `window_days` from config,
    default 7. Query: `search.json?q=after:{since_date} before:{until_date}&page=N`.
  - A page is the last one when `grouped_search_result.more_full_page_results` is not true. A
    `grouped_search_result.error` raises `TransformError`.
  - Post ids are grouped by `topic_id` and fetched from `{base_url}/t/{topic_id}/posts.json?post_ids[]=…` in
    chunks of 20. If `posts.json` leaves out any requested post, that is a `TransientError` (retry later). An
    unexpected response shape from either endpoint is also a `TransientError`.
  - `topic_title` is attached to each post payload from `search["topics"]`, falling back to the hit's
    `topic_title_headline` with tags stripped.
  - Non-final pages carry the starting cursor unchanged; only the final page moves it, to newest `created_at`
    seen minus 60 s (or to the window end, if the window closed before `now` and that is later). Discourse
    search order is not guaranteed oldest-first, so a per-page cursor could skip posts after a crash
    (ADR-003 rule 4). The 60-second overlap re-fetches boundary posts; idempotency absorbs them.
  - At most 20 search pages per poll. A window that hits the cap never reaches its final page, so the cursor
    stays unchanged; lower `window_days` if that happens. Both limits are marked `# ponytail:`.
  - 429/5xx from the port surface as `TransientError` and stop the iterator; the cursor of already-yielded
    pages is kept by the caller.

### Playstore (`connectors/playstore.py`) — push (fixtures), `kind=review`
- Shape mirrors the Play Developer API review object: `reviewId: str, authorName: str | None, comments:
  list[{userComment: {text: str, lastModified: {seconds: NaiveUtc}, starRating: int, reviewerLanguage: str | None,
  device: str | None, androidOsVersion: str | None, appVersionName: str | None}}]`. Uses the first comment.
- `external_id = reviewId`; `external_event_id = f"{reviewId}:{lastModified.seconds.isoformat()}"`.
- `rating = starRating`, `language = reviewerLanguage`, `text = userComment.text`, `title = None`,
  `source_created_at = source_updated_at = lastModified` (the `NaiveUtc` field turns the epoch into naive UTC).
- `metadata = PlaystoreMetadata(app_version=appVersionName, device, android_os_version)`.
  (ADR note: real Play has no review webhook; reviews are polled via the Reply-to-Reviews API. Fixtures stand in
  for that poller; the transform is identical either way. Say this before the interviewer does.)

### Twitter (`connectors/twitter.py`) — push (fixtures), `kind=post`
- Input `TweetIn`: `id: str, text: str, created_at: datetime, lang: str | None, author: {id: str, username: str},
  edit_history_tweet_ids: list[str] = [], public_metrics: {retweet_count: int = 0, like_count: int = 0},
  country: str | None`.
- `external_id = edit_history_tweet_ids[0] if edit_history_tweet_ids else id` so an edit updates the original
  record instead of creating a second one; `external_event_id = f"{id}:{created_at.isoformat()}"` (each edit
  has a new id, so each edit is a new raw event).
- `author = @username`, `language = lang`, `metadata = TwitterMetadata(country, retweets, likes)`.
  (ADR note: real Twitter webhooks need a CRC challenge handshake; fixtures stand in.)

### Intercom (`connectors/intercom.py`) — push (fixtures), `kind=conversation`
- Input `IntercomEventIn`: `topic: str, data: {item: {id: str, created_at: NaiveUtc, updated_at: NaiveUtc, state: str,
  source: {subject: str | None, body: str, author: {name: str | None}}, conversation_parts:
  {conversation_parts: list[{id: str, body: str | None, created_at: NaiveUtc, author: {name: str | None}}]},
  tags: {tags: list[{name: str}]}}}`. Real Intercom conversation webhooks carry the whole conversation with
  its parts, so every payload is a full snapshot and the normal upsert applies (ADR-002).
- `topic == "ping"` → empty list (fixture `intercom/ping.json`); `conversation.*` → one record from the
  snapshot; any other topic → `TransformError` (the event goes dead).
- `external_id = item.id`; `external_event_id = f"{item.id}:{item.updated_at.isoformat()}:{payload_hash(item)[:12]}"`,
  so two different snapshots with the same `updated_at` are not deduplicated into one.
- `text` = source body + each part body, HTML stripped, joined by blank lines in time order; `title = subject`;
  `author = source.author.name`; `source_created_at/updated_at` from the epoch fields.
- `metadata = IntercomMetadata(part_count, tags, state)`.

Metadata models in `domain/metadata.py` get adjusted to match: Playstore `(app_version, device,
android_os_version)`, Twitter `(country, retweets, likes)`, Intercom `(part_count, tags, state)`, Discourse
`(topic_id, post_number, like_count, url)`. No metadata field repeats a record column (title, author,
external_id). Phase 1 may have shipped slightly different field lists; this phase is
allowed to edit `domain/metadata.py` to the lists above.

## Utils added
- `utils/html.py`: `strip_tags(html: str) -> str` on stdlib `html.parser.HTMLParser`, collapses whitespace.
- No epoch helper in `utils/time.py`: epoch fields are typed `NaiveUtc` on the input models
  (`domain/models.py`), so Pydantic converts them.

## Tests
- `tests/unit/connectors/test_contract.py`: parametrised over `CONNECTORS.values()` × every file in
  `tests/fixtures/<source_type>/`; asserts the rules in "Connector contract" above plus
  `set(SourceType) == set(CONNECTORS)` and that every pull-mode-capable type is in `PULLERS`.
- `tests/unit/connectors/test_<source>.py` (four files): golden assertions on the specific fields for one
  fixture each (text, kind, external_id, rating/language, metadata values, url), the tombstone case for
  Discourse, the edit-id case for Twitter, the ping → empty case for Intercom, and `malformed.json` →
  `ValidationError` for each.
- `tests/unit/connectors/test_discourse_pull.py` and `test_discourse_pull_errors.py`: a stub `HttpClient`
  (dict of url→response) proving: pages are yielded with cursors, topic titles are attached, posts are
  requested 20 at a time, the page cap leaves the cursor unchanged, an omitted post stops the pull, and a
  `TransientError` on page 2 stops after page 1 with page 1's cursor intact.
- `tests/unit/test_html.py`: strip_tags on nested tags, entities, and whitespace.

## Files
```
feedback_ingest/connectors/{base,registry,discourse,discourse_models,discourse_pull,playstore,twitter,intercom}.py
feedback_ingest/utils/html.py
feedback_ingest/domain/metadata.py (field lists aligned)
tests/fixtures/{discourse,playstore,twitter,intercom}/*.json   (≥2 per source incl. malformed.json; synthetic)
tests/unit/connectors/{test_contract,test_registry,test_discourse,test_playstore,test_twitter,test_intercom,test_discourse_pull,test_discourse_pull_errors}.py
tests/unit/test_html.py
```

## How to explain this phase in the interview
"A connector turns a raw dict into feedback records. It validates the payload with a Pydantic model first, so a
bad payload fails at one obvious line and goes to the dead-letter list instead of being retried forever. A dict
maps each source type to its connector, so nothing else in the system knows which sources exist. Discourse's
connector can also pull, page by page, and each page carries the cursor to store once that page is safely
written. Adding Zendesk is one file, one metadata model, one registry entry and one fixture; the contract test
fails until all four are there."

## Deviations recorded at implementation (code wins over the text above)
- Pull cursor moves only on the final page, and the search window is bounded (see the Discourse section).
  The `now + 1 day` upper bound is there because Discourse's `before:` excludes that date. To be confirmed by
  the Phase 4 live test.
- The topic title lives only in `record.title` (from `search["topics"]`, else the headline, so it may be null);
  `PlaystoreMetadata.android_os_version` is an int (API level); developer replies in Playstore `comments` are dropped, the first `userComment` is used.
- `check_source` raises `ValueError` (there is no `ConfigError`). The push-secret check is not in
  `check_source` because the `Source` model already rejects a push source without a secret.
- There is no `connector_for`/`puller_for`; the registry completeness test guarantees `CONNECTORS[t]` exists.
- `external_event_id` validates with the input model and falls back to `payload_hash` on `ValidationError`, so
  it never raises. Missing `base_url`/`start_after` config or an unparseable cursor raises `TransformError`.
- Twitter edits set `source_updated_at=None`; the edit's later `created_at` decides the winning version, and
  the store keeps the original creation time. Twitter delete tombstones are not built (no delete fixture shape).
- `HttpxClient` builds the URL with `httpx.URL(url).copy_merge_params(params)` (or the bare URL when `params`
  is empty), because httpx's `params=` replaces a query string already in the URL; `posts.json?post_ids[]=…`
  relies on this.
- Empty `text` is allowed: an image-only post or a rating with no words is still feedback.
- Fleet 2: a Playstore review with no user comment raises `TransformError("review has no user comment")`
  and goes dead (it used to return `[]`); a bad payload must not look like "no data".
- Connector files split into `discourse.py` + `discourse_models.py` + `discourse_pull.py`; registry tests live
  in `test_registry.py`; pull error tests in `test_discourse_pull_errors.py`.
