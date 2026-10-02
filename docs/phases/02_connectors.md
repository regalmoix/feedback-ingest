# Phase 2 — Connectors and transform

Status: implemented 2026-10-03 (commit 6264b45), review in progress. Depends on Phase 1 and ADR-003 (ADR-003 is authoritative where they differ). Still no HTTP endpoints.

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
    def external_event_id(self, payload: dict[str, Any]) -> str: ...
    def transform(self, source: Source, payload: dict[str, Any]) -> list[FeedbackRecord]: ...
    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool: ...

class PullConnector(SourceConnector, Protocol):
    def pull(self, source: Source, http: HttpClient, now: datetime) -> Iterator[PullPage]: ...

def default_verify_signature(secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
    # HMAC-SHA256 hex of the raw body, header "X-Signature"; uses utils.signing.verify
```
Rules every connector obeys (these are the contract test):
- `external_event_id` is `f"{item id}:{updated-or-created timestamp}"` when the payload has them, else
  `utils.hashing.payload_hash(payload)`. Reason: a bare item id would make a re-pulled *edited* post collide on
  the raw_events unique key and be silently dropped, so the record would never update.
- `transform` returns a list: empty for payloads that are not feedback (ping, bot message), one record normally,
  several when one payload holds several items, and a record with `deleted_at` set for a deletion.
- `transform` lets Pydantic's `ValidationError` propagate for malformed payloads and raises `TransformError` for
  any other permanent problem; the worker (Phase 3) catches both in one `except` and marks the event dead. It
  never raises anything else on bad data.
- `transform` is deterministic: same input, same output. Connectors are clock-free: `ingested_at` is a required
  field, so connectors set it from `source_created_at` as a placeholder and the pipeline (Phase 3) overwrites it
  with the real clock before upsert. `id` is `uuid4().hex` per record and is excluded from the determinism check.
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
Callers index the dicts directly: `CONNECTORS[source.type]`, `PULLERS[source.type]`. `check_source` runs at
Source creation and also checks the puller's `required_config` keys (Discourse: `base_url`, `start_after`)
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
  `utils/html.strip_tags` (stdlib `html.parser`).
- `external_id = str(id)`; `external_event_id = f"{id}:{(updated_at or created_at).isoformat()}"`.
- `metadata = DiscourseMetadata(topic_id, post_number, like_count, url)` where
  `url = f"{source.config['base_url']}/t/{topic_slug}/{topic_id}/{post_number}"`.
- `title = topic_title`, `author = name or username`, `language = None`, `rating = None`.
- `deleted_at` present → record with `deleted_at` set (tombstone fixture: `discourse/post_deleted.json`).
- `pull(source, http, now)`: `since = source.cursor or source.config["start_after"]` (ISO date);
  GET `{base_url}/search.json?q=after:{since_date} before:{now_date}&page=N` until `posts` is empty or shorter
  than the page; group post ids by `topic_id`; GET `{base_url}/t/{topic_id}/posts.json?post_ids[]=…` per
  topic; attach `topic_title` from the search hit (`topic_title_headline`, tags stripped) to each post payload.
  Yield one `PullPage` per search page with `cursor = (max created_at seen so far minus 60s).isoformat()`.
  The 60-second overlap re-fetches boundary posts; idempotency absorbs them. 429/5xx from the port surface as
  `TransientError` and stop the iterator; the cursor of already-yielded pages is kept by the caller.
  `# ponytail: full re-scan of each search page; store last post id per topic if Discourse volume grows`.

### Playstore (`connectors/playstore.py`) — push (fixtures), `kind=review`
- Shape mirrors the Play Developer API review object: `reviewId: str, authorName: str | None, comments:
  list[{userComment: {text: str, lastModified: {seconds: int}, starRating: int, reviewerLanguage: str | None,
  device: str | None, androidOsVersion: str | None, appVersionName: str | None}}]`. Uses the first comment.
- `external_id = reviewId`; `external_event_id = f"{reviewId}:{lastModified.seconds}"`.
- `rating = starRating`, `language = reviewerLanguage`, `text = userComment.text`, `title = None`,
  `source_created_at = source_updated_at = lastModified` (epoch → naive UTC).
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
- Input `IntercomEventIn`: `topic: str, data: {item: {id: str, created_at: int, updated_at: int, state: str,
  source: {subject: str | None, body: str, author: {name: str | None}}, conversation_parts:
  {conversation_parts: list[{id: str, body: str | None, created_at: int, author: {name: str | None}}]},
  tags: {tags: list[{name: str}]}}}`. Real Intercom conversation webhooks carry the whole conversation with
  its parts, so every payload is a full snapshot and the normal upsert applies (ADR-002).
- `topic` not starting with `conversation.` → empty list (e.g. `ping`). Fixture `intercom/ping.json` proves it.
- `external_id = item.id`; `external_event_id = f"{item.id}:{item.updated_at}"`.
- `text` = source body + each part body, HTML stripped, joined by blank lines in time order; `title = subject`;
  `author = source.author.name`; `source_created_at/updated_at` from epochs.
- `metadata = IntercomMetadata(part_count, tags, state)`.

Metadata models in `domain/metadata.py` get adjusted to match: Playstore `(app_version, device,
android_os_version)`, Twitter `(country, retweets, likes)`, Intercom `(part_count, tags, state)`, Discourse
`(topic_id, post_number, like_count, url)`. No metadata field repeats a record column (title, author,
external_id). Phase 1 may have shipped slightly different field lists; this phase is
allowed to edit `domain/metadata.py` to the lists above.

## Utils added
- `utils/html.py`: `strip_tags(html: str) -> str` on stdlib `html.parser.HTMLParser`, collapses whitespace.
- `utils/time.py`: add `from_epoch(seconds: int) -> datetime` (naive UTC).

## Tests
- `tests/unit/connectors/test_contract.py`: parametrised over `CONNECTORS.values()` × every file in
  `tests/fixtures/<source_type>/`; asserts the rules in "Connector contract" above plus
  `set(SourceType) == set(CONNECTORS)` and that every pull-mode-capable type is in `PULLERS`.
- `tests/unit/connectors/test_<source>.py` (four files): golden assertions on the specific fields for one
  fixture each (text, kind, external_id, rating/language, metadata values, url), the tombstone case for
  Discourse, the edit-id case for Twitter, the ping → empty case for Intercom, and `malformed.json` →
  `ValidationError` for each.
- `tests/unit/connectors/test_discourse_pull.py`: a stub `HttpClient` (dict of url→response) proving: pages
  are yielded with cursors, topic titles are attached, a `TransientError` on page 2 stops after page 1 with
  page 1's cursor intact.
- `tests/unit/test_html.py`: strip_tags on nested tags, entities, and whitespace.

## Files
```
feedback_ingest/connectors/{base,registry,discourse,playstore,twitter,intercom}.py
feedback_ingest/utils/html.py (+ from_epoch in utils/time.py)
feedback_ingest/domain/metadata.py (field lists aligned)
tests/fixtures/{discourse,playstore,twitter,intercom}/*.json   (≥2 per source incl. malformed.json; synthetic)
tests/unit/connectors/{test_contract,test_discourse,test_playstore,test_twitter,test_intercom,test_discourse_pull}.py
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
- Pull cursor: non-final pages return the starting cursor; only the final page moves it to newest `created_at`
  minus 60 s, because Discourse search order is not guaranteed oldest-first and a per-page cursor could skip
  posts after a crash (ADR-003 rule 4). Marked `# ponytail:`.
- Search window uses `before:{now + 1 day}` because Discourse's `before:` excludes that date. To be confirmed by
  the Phase 4 live test.
- The topic title lives only in `record.title` (posts.json has no title, so it may be null);
  `PlaystoreMetadata.android_os_version` is an int (API level); developer replies in Playstore `comments` are dropped, the first `userComment` is used.
- `check_source` raises `ValueError` (there is no `ConfigError`). The push-secret check is not in
  `check_source` because the `Source` model already rejects a push source without a secret.
- There is no `connector_for`/`puller_for`; the registry completeness test guarantees `CONNECTORS[t]` exists.
- `external_event_id` validates with the input model and falls back to `payload_hash` on `ValidationError`, so
  it never raises. Missing `base_url`/`start_after` config raises `TransformError` (event goes dead).
- Twitter edits set `source_updated_at=None`; the edit's later `created_at` decides the winning version, and
  the store keeps the original creation time. Twitter delete tombstones are not built (no delete fixture shape).
- `HttpxClient` passes `params=params or None` because httpx drops a query string already in the URL when
  `params` is given, even empty; `posts.json?post_ids[]=…` relies on this.
- Empty `text` is allowed: an image-only post or a rating with no words is still feedback.
- Connector files split into `discourse.py` + `discourse_models.py`; registry tests live in `test_registry.py`.
