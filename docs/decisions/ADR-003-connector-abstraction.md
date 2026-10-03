# ADR-003: Connector abstraction

## Status
Accepted (council-reviewed, 2026-10-03)

## Context

The brief scores extensibility as "how easy it is to add a new type of feedback source". The connector is our answer to that. It is also the part the interviewer will push on hardest.

A **connector** is the code for one source type. A **Source** is one tenant's configured instance of that type. Two Playstore apps for one tenant are two Source rows that share one connector.

The four sources, and what the real services do:

| Source | Mode in this project | What the real service does |
|---|---|---|
| Discourse | pull, live | We poll `search.json`, then `t/{topic}/posts.json`. Discourse also has webhooks, signed with `X-Discourse-Event-Signature: sha256=<hex>`. |
| Playstore | push, fed from fixture files | **Google Play has no review webhook.** Reviews are read by polling the Reply to Reviews API. Fixtures stand in for that poller. |
| Twitter | push, fed from fixture files | **Twitter webhooks need a CRC handshake first**: a GET we must answer with an HMAC of a token. Fixtures stand in for a poller. `country` is top-level in our fixture; a real v2 payload carries it under `includes.places`, so a real connector reads it there; fixtures stand in. |
| Intercom | push, fed from fixture files | Real webhooks, signed with HMAC-SHA1 in `X-Hub-Signature: sha1=<hex>`. |
| Custom (added later) | push | Enterpret's public custom webhook shape: a batch `{"records": [...]}`. Their docs describe an `api-key` header; ours uses the per-source URL and HMAC instead. |

Our demo script posts the fixtures to our own webhook URL. `scripts/sign.py` signs each body with our default scheme (it only signs; it does not send). The transform is the same code whichever way a payload arrives.

Already fixed before this review:
- Python 3.12, Pydantic v2, `mypy --strict`, no speculative abstractions.
- A `typing.Protocol` per capability plus a registry dict. This is the extensibility story and it stays.
- Every inbound payload, push or pull, is saved in `raw_events` as parsed JSON before we answer (not the raw bytes, so the signature cannot be re-checked from storage; a pulled Discourse post also carries the topic title we add). A worker transforms it later (ADR-001).
- `raw_events` is unique on `(source_id, external_event_id)`. `FeedbackRecord` is unique on `(source_id, external_id)` and has `deleted_at`, `connector_version` and `source_updated_at` (ADR-002).
- `FeedbackStore.upsert` only overwrites when `COALESCE(source_updated_at, source_created_at)` is newer or equal (applied in Python by `merge` inside `BEGIN IMMEDIATE`; see ADR-002). So out-of-order webhooks cannot overwrite a newer record.
- `Source` has `mode`, `config: dict[str, str]`, `webhook_secret` and `cursor: str | None`. The `HttpClient` and `Clock` ports exist.

Jargon used below:
- **Protocol**: a Python type that lists methods. Any class with those methods fits it. Nothing is inherited.
- **Registry**: a plain dict from `SourceType` to the connector object.
- **Ingress**: how bytes get into `raw_events` (webhook or poll).
- **Cursor**: a bookmark string that says where the next poll should start.
- **HMAC**: a signature made from the request body and a shared secret. It proves the sender knows the secret.
- **Input model**: a Pydantic model shaped like the payload the source really sends.
- **Dead**: a raw event that failed for a reason retrying cannot fix. It stays stored and can be replayed after a fix.
- **Contract test**: one test that runs every connector against every fixture and checks the rules below.

## Decision

### The contract (`feedback_ingest/connectors/base.py`)

Built version (updated after Fleet 2; imports trimmed):

```python
class PullPage(FrozenModel):
    payloads: list[dict[str, Any]]
    cursor: str  # saved only after this page's raw rows are committed


def default_verify_signature(secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
    return signing.verify(secret, body, headers.get("X-Signature", ""))


class SourceConnector(Protocol):
    source_type: ClassVar[SourceType]
    version: ClassVar[int]
    required_config: ClassVar[tuple[str, ...]]

    def external_event_id(self, payload: Mapping[str, Any]) -> str: ...
    def transform(self, source: Source, payload: Mapping[str, Any]) -> list[FeedbackRecord]: ...
    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool: ...


class PullConnector(SourceConnector, Protocol):
    pull_config: ClassVar[tuple[str, ...]]  # extra config keys a pull-mode Source must have

    def pull(
        self, source: Source, http: HttpClient, clock: Clock, deadline: datetime
    ) -> Iterator[PullPage]: ...


def new_record(
    source: Source, connector: SourceConnector, external_id: str, **content: Unpack[RecordContent]
) -> FeedbackRecord:
    # identity keys go last so content cannot override them; the pipeline stamps ingested_at
    return FeedbackRecord.model_validate(
        {
            "kind": KIND_BY_SOURCE.get(connector.source_type),
            **content,
            "id": uuid5(NAMESPACE_URL, f"{source.id}:{external_id}").hex,
            "tenant_id": source.tenant_id,
            "source_id": source.id,
            "source_type": connector.source_type,
            "external_id": external_id,
            "connector_version": connector.version,
            "ingested_at": content["source_created_at"],
        }
    )
```

`RecordContent` is a `TypedDict` of the content fields (title, text, author, language, rating, the three timestamps, metadata, and an optional kind (custom only)); `kind` defaults to the source type's entry in `KIND_BY_SOURCE`. `version` is bumped when transform output changes and is stamped on every record. `required_config` lists the config keys every Source of this type must have. `deadline` is the wall-clock budget for one sync (`FI_PULL_DEADLINE_SECONDS`, default 60).

A connector that uses the default signature delegates to it in two lines:

```python
    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
        return default_verify_signature(secret, body, headers)
```

### The two registries (`feedback_ingest/connectors/registry.py`)

```python
_DISCOURSE: PullConnector = DiscourseConnector()
CONNECTORS: dict[SourceType, SourceConnector] = {
    c.source_type: c
    for c in (
        _DISCOURSE,
        PlaystoreConnector(),
        TwitterConnector(),
        IntercomConnector(),
        CustomConnector(),
    )
}
PULLERS: dict[SourceType, PullConnector] = {SourceType.DISCOURSE: _DISCOURSE}
```

Callers index the dicts directly (`CONNECTORS[source.type]`, `PULLERS[source.type]`); there is no `connector_for` or `puller_for` helper. The keys come from each connector's own `source_type`, so a key cannot drift from its value. mypy checks each object against the Protocol at the dict annotation (and the puller at the `_DISCOURSE: PullConnector` annotation). A missing method or a missing `version` is a type error on that line.

Configuration-time check, run when a Source is created (the API turns it into a 422):

```python
def check_source(source: Source) -> None:
    required = CONNECTORS[source.type].required_config
    if source.mode is SourceMode.PULL:
        if source.type not in PULLERS:
            raise ValueError(f"{source.type} cannot pull")
        required += PULLERS[source.type].pull_config
    for key in required:
        if key not in source.config:
            raise ValueError(f"{source.type} {source.mode} source needs config[{key!r}]")
    ...  # base_url is http(s), no credentials, not an internal host; window_days 1 to 31; start_after parses
```

A push source without a `webhook_secret` is rejected by the `Source` model itself, so `check_source` does not repeat that check. `POST /v1/sources` rejects a pull source that is given a `webhook_secret` (422), because webhooks are push-only.

### The nine rulings

1. **Transform cardinality: `transform(source, payload) -> list[FeedbackRecord]`.** It returns 0 to N records. A ping, bot message or non-feedback event is an empty list, and the worker marks it processed. A payload that should hold feedback but does not (a Play Store review with no user comment) is not an empty list: it raises and goes dead. A deletion is a full record with `deleted_at` set, and the store never clears `deleted_at` (ADR-002). One payload holding several items returns several records. We do not add a result type, because a list already covers skip, one, many and delete.

2. **Raw-event identity: `external_event_id = f"{item id}:{updated_at or created_at}"` when the payload has them, else `payload_hash(payload)`.**
   - Why: `raw_events` drops any second insert with the same key. If the key were the bare post id, an edited Discourse post pulled again would collide with the first pull's row. It would be dropped silently, the worker would never see the edit, and the record would never update.
   - With the timestamp in the key, an edit is a new raw event. An unchanged post re-pulled in the overlap window has the same key and is dropped, which is what we want.
   - `external_event_id` runs at ingress on a payload nobody has validated yet. It must never raise. If either field is missing it returns the payload hash. A malformed payload is still stored, then goes dead in the worker with a clear error.
   - `external_id` (record identity) stays the bare item id. Twitter's stays the original tweet id (ADR-002).
   - Built variations: Intercom adds the first 12 hex characters of the item's hash, so two snapshots with the same `updated_at` stay apart. The custom connector always uses the hash of the whole batch, because one push is one raw event.

3. **Signature verification: an optional per-connector `verify_signature(secret, body, headers) -> bool`.** The default is HMAC-SHA256, hex, over the raw body, in header `X-Signature`. It is written once, as `default_verify_signature`, and each connector delegates to it unless its source signs differently. None of the connectors override it in this project, because `scripts/sign.py` signs fixtures with the default. The hook is where real schemes go:
   - **Intercom**: compute HMAC-SHA1 over the body, read `X-Hub-Signature`, strip `sha1=`, compare with `hmac.compare_digest`.
   - **Discourse webhooks**: read `X-Discourse-Event-Signature`, strip `sha256=`, then compare as the default does.
   - **Zendesk**: HMAC-SHA256 over the timestamp header plus the body, base64, in `X-Zendesk-Webhook-Signature`.
   - **Twitter's CRC handshake** is a GET challenge, not a signature check. It is an extension (a `handshake` method), added only if Twitter becomes a real webhook.
   - The algorithm belongs to the source type, so it lives on the connector. The secret belongs to the tenant's instance, so it lives on the Source row.

4. **Pull shape: `pull(source, http, clock, deadline) -> Iterator[PullPage]`, where `PullPage(payloads, cursor)`.** (Fleet 2 replaced `now` with `clock` and `deadline`.)
   - The poll service enqueues one page's payloads and commits them. Only then does it save `page.cursor`.
   - Built: Discourse holds the cursor back until the final page of its search window (see the last point below). So if a call fails mid-window, the stored cursor has not moved, and the next tick restarts the whole window. The payloads already accepted stay in `raw_events`, and rule 2 drops them when they come again.
   - Pull treats permanent and transient upstream errors the same today: stop, keep the cursor, put the message in `PullResult.error`, retry on the next tick.
   - Limits: at most 10 search pages per window (Discourse answers 400 for page 11), about 500 posts per day. A busier window raises "lower window_days via PATCH" and the cursor does not move. The deadline is checked before every search page and every `posts.json` call.
   - If the process crashes between the commit and the cursor save, the page is fetched again. Rule 2 drops the repeats.
   - The PDF sample search response omits `grouped_search_result`; the live API always sends it and we require it so a missing one is never read as the last page; a mock built from the PDF sample fails loudly, not silently.
   - A page's cursor must be safe to resume from: everything older than it is in this page or an earlier one. With oldest-first pages, that is the page's newest timestamp minus a small overlap. If a source only sorts newest-first, the connector holds the cursor back and yields it on the final page.

5. **Registries: `CONNECTORS` and `PULLERS`, built from a tuple of instances, as above.** The dict is keyed by type, so one type maps to exactly one connector. `tests/unit/connectors/test_registry.py` asserts `set(SourceType) == CONNECTORS.keys()`, that every type except `custom` has a `KIND_BY_SOURCE` entry, that `PULLERS.keys() <= CONNECTORS.keys()`, and that every type has a `malformed` fixture. `check_source` rejects a pull-mode Source whose type has no puller, any Source that lacks a key in its connector's `required_config` (plus the puller's `pull_config` in pull mode), and config values that do not pass (`start_after`, `window_days` 1 to 31, a `base_url` that is not http(s), has credentials, or names an internal host). There is no `isinstance` discovery.

6. **Input models: every connector validates first.** `transform` starts with `PlaystoreReviewIn.model_validate(payload)` (or `DiscoursePostIn`, `TweetIn`, `IntercomEventIn`, `CustomBatchIn`), then maps plain typed fields. Input models use `extra="ignore"`. Why: under `mypy --strict`, `payload["review"]["text"]` is `Any`, so it passes the type check without checking anything. A `ValidationError` is a permanent failure. The worker catches `ValidationError` next to `PermanentError` and marks the event dead. That is one `except` clause in the worker, not one per connector, and it also catches a bad `FeedbackRecord` or metadata model.

7. **What `transform` receives: the whole `Source`, with `webhook_secret: SecretStr | None`.** The risk is a log line or exception message that prints a Source and leaks the secret. A slimmer `SourceRef` model would protect only the transform. `SecretStr` prints `**********` everywhere: logs, `repr`, the API. It is a one-word type change and adds no model. The router calls `get_secret_value()` once, to verify. The SQL store must write `get_secret_value()` too, because `model_dump(mode="json")` would store the asterisks. A round-trip test covers that. A transform reads only `tenant_id`, `id` and `config`. It never reads `cursor`.

8. **Webhook routing, end to end** (amended in Phase 6: a webhook authenticates like a real one, with no API key):
   1. `POST /v1/sources/{source_id}/events` arrives with `X-Signature` and no `X-API-Key`. A real sender (Intercom, Zendesk) cannot add our header.
   2. `SourceStore.get_by_id(source_id)`. An unknown id gives 404. The id is an unguessable uuid, so it picks the source but proves nothing by itself.
   3. Webhooks are push-only (amended in Fleet 2): a pull-mode source gives 409 "source does not accept webhooks", before any signature check, and `POST /v1/sources` rejects a `webhook_secret` on a pull source with 422. A push source always has a secret (the `Source` model requires one).
   4. `CONNECTORS[source.type].verify_signature(secret, raw_body_bytes, headers)` runs on the raw bytes, before JSON parsing. A failure gives 401. This is what proves the caller. Only then does a disabled source give 409, so source state is told only to a caller who proved itself.
   5. We parse the JSON (400 if it is not an object or is nested too deep), compute `external_event_id`, and call `RawEventQueue.enqueue`. It returns `Enqueued(id, status)`, the stored row's id and status (the existing row on a duplicate). New or duplicate, the reply is 202 with that id. The signature check, the parse and the insert run in the threadpool. A body over 1 MiB is refused with 413 before any of this.
   6. Later, the worker claims the row, loads the Source, calls `transform`, upserts each record, and marks the event processed. A `ValidationError` or `PermanentError` marks it dead. A `TransientError` marks it failed and schedules a retry.
   - Tenant isolation: the raw event's `tenant_id` comes from the source row, and only a caller holding that source's secret can write to it. Every other route still resolves the tenant from `X-API-Key`.

9. **Known limit: `FeedbackKind` is where the design strains.** An NPS survey with a 0 to 10 score does not fit `review | conversation | post`. (Built later: the custom connector added the `survey` kind as one enum value, with the score in `CustomMetadata.score`. No migration was needed.) The answer: "a new kind is an enum value plus optional fields in metadata; the record is the extension point that costs most". Adding the enum value needs no migration, because `kind` is stored as text. The real cost comes when the new kind needs a field everyone queries, like an NPS score. That field becomes a new common column, which means a migration plus a replay. That cost is in the record, not in the connector.

### Small consequences for the Phase 1 models

- `Source.webhook_secret` becomes `SecretStr | None` (ruling 7).
- `transform` stays free of clocks and random ids, so the same input always gives the same output. The connector builds each record with `new_record(source, connector, external_id, **content)`, which sets `id` to a `uuid5` of the source id and external id, so it is deterministic. The pipeline stamps only `ingested_at` (built as `model_validate(record.model_dump() | {"ingested_at": now})`, so the stamped record is validated again). The contract test compares whole records.

## Where the council agrees

- Keep the Protocol plus registry dict. The dict is a dispatch table, and that is the honest answer to "isn't this an if/else?" (Executor, Outsider, First Principles, Expansionist).
- "Generic HMAC for all sources" is false. Make verification an optional method with an HMAC default (all five).
- Adopt alternative (d), per-source input models, inside `transform` (Executor, Contrarian, First Principles, Expansionist).
- Versioning means: bump `version`, then replay `raw_events` (Executor, Outsider, First Principles, Expansionist).
- Test with one shared contract test run over the registry and the fixtures. No mocks (Executor, First Principles, Expansionist).
- Reject plugin discovery (e) and declarative mapping (b) for now (Executor, First Principles; the Expansionist would keep (b) for later).
- Say plainly that Play Store has no review webhook and fixtures stand in (Contrarian, Outsider).
- Out-of-order webhooks need a last-write-wins guard (Contrarian). It already exists in `FeedbackStore.upsert` (ADR-002).

## Where the council clashes

1. **One record or a list?** The proposal, Executor and Expansionist return one record. The Contrarian says zero, many or a tombstone. **Ruling: a list** (ruling 1). A payload that is not feedback has no honest single-record answer.
2. **Is pull a subtype or a separate job?** First Principles says `PullConnector(SourceConnector)` mixes ingress back into transform. The Executor keeps the subtype. **Ruling: keep the subtype, use the First Principles framing to explain it.** Every puller must transform what it fetches, so the two belong in one class. Push or pull is still chosen by `Source.mode`. `PULLERS` keeps the type information, and `check_source` keeps mode and capability in step.
3. **Inherit from the Protocol explicitly?** The Executor wants explicit inheritance, so errors show up at the class and a default method can live on the Protocol. The Outsider wants to be able to say "connectors inherit nothing". **Ruling: structural, no inheritance.** mypy still catches a broken connector at the registry tuple. The signature default is a module function that connectors call, so nothing needs inheriting.
4. **`runtime_checkable` + `isinstance` (Expansionist) or static registries (Executor)?** **Ruling: static.** `isinstance` on a Protocol only checks that method names exist, not their signatures. It is weaker than mypy, and it is just the if/else in another form.
5. **Grow the abstraction or keep it small?** The Expansionist wants Config models and a MappedConnector. The Executor, Outsider and First Principles want it small. **Ruling: small.** `config: dict[str, str]` plus `check_source` covers four sources. Everything else is listed as an extension.
6. **Does transform get the whole Source?** The Contrarian says give it only `tenant_id` and `source_id`. **Ruling: whole Source, with `SecretStr`** (ruling 7). That fixes the leak everywhere, not only in the transform.
7. **Is `external_event_id` connector logic or ingress logic?** First Principles says it is identity at ingress. **Ruling: both are right.** It stays on the connector, because only the connector knows where the id is in the payload. It runs at ingress, must never raise, and includes the timestamp (ruling 2).
8. **Does Play push reviews?** The Executor said Play delivers through Pub/Sub push with an OIDC token. The Contrarian said Play has no review webhook. **Ruling: the Contrarian is right.** Play's Pub/Sub notifications cover purchases and subscriptions, not reviews.
9. **Add `handshake()` now (Contrarian)?** **Ruling: no.** No source in this project has a live webhook that needs one. It is named as an extension.

## Blind spots the council caught

These came out of the peer reviews. No single response had them.

- **The dedup key silently drops edits** (Executor review). Fixed by ruling 2.
- **How a webhook finds its tenant and secret before verifying** (raised in four of the five reviews). Fixed by ruling 8. Tenant isolation lives at the source lookup.
- **No one sketched request to `raw_events` to worker to record, end to end** (Outsider review). Ruling 8 is that sketch.
- **The record, not the connector, is the extension point that will strain** (First Principles review). Recorded as ruling 9.
- **Push sources that only send a delta must fetch** (Contrarian review). That would put HTTP inside a pure transform. Answer: such a source is modelled as a puller whose webhook only marks it due for a poll. None of the four need this, because Intercom sends the full conversation (ADR-002).
- **Backfill for a newly connected push source** (Contrarian and Expansionist reviews). This is an extension: run the source's poller once. Named, not built.
- **Shadow-running v2 next to v1** (Expansionist review). Because raw is kept, running v2's transform over stored raw events and diffing against stored records is a script, not a feature. Named as the strong form of the versioning answer.

Chairman additions, found while checking the rulings:
- `external_event_id` runs on unvalidated input, so it must never raise (ruling 2).
- A page cursor taken from newest-first results would skip unfetched pages after a crash (ruling 4).
- The Discourse poller searches by creation date, so an edit to an old post is missed until a periodic re-scan. Ruling 2 is what makes that re-scan safe. Without it, every edit in the re-scan would be dropped.
- Real third-party senders (Intercom, Zendesk) cannot add our `X-API-Key` header. So the webhook does not ask for it (ruling 8 as amended): the unguessable `source_id` in the path plus that source's signature authenticate the call, and the tenant comes from the source row.

## Rejected alternatives and why

| Alternative | Why not |
|---|---|
| (a) Abstract base class with template methods | It hides the control flow in the base class, and each source ends up fighting the template (Intercom joins parts, Twitter remaps ids). A Protocol gives the same type check with no shared state. |
| (b) Declarative JSON-path field mapping | Field mapping is not the hard part. Identity, edits, threading, completeness and paging are. Discourse needs two calls per topic. The mapping would grow into a small language that needs its own tests. Extension: a mapped connector could satisfy the same Protocol later. |
| (c) Separate Fetcher and Transformer classes | Twice the registration for no gain. A fetcher must produce payloads its own transformer understands, so they belong together. `PULLERS` already gives the split where it matters. |
| (d) Per-source Pydantic input models | **Adopted** (ruling 6). |
| (e) Plugin discovery via entry points | Nobody installs third-party connectors here. A static dict can be searched, type-checked and tested for completeness. |
| Expansionist: a Config model per connector | `dict[str, str]` plus `check_source` is enough for four sources. Extension: a per-connector Config model, which gives a JSON schema and a self-serve form. |
| Expansionist: `MappedConnector` | Same as (b). |
| Expansionist: `runtime_checkable` `WebhookVerifier` found by `isinstance` | It checks only that a method name exists, which is weaker than mypy. A two-line delegate does the same job. |
| Expansionist: `ReplyConnector` write-back, Backfill capability | Not in the brief. Named as extensions: each would be one more Protocol and one more registry. |
| Expansionist: shadow-running v2 | A script over `raw_events`, not a feature. Used as an interview answer. |
| Contrarian: a result type with skip and delete cases | A list already covers skip (empty), delete (`deleted_at`) and many. |
| Contrarian: a separate PUSH registry | Every connector can transform a pushed payload, so a push registry would just copy `CONNECTORS`. |
| A slim `SourceRef` model for transform | `SecretStr` fixes the leak everywhere with no new model. |
| Executor: explicit Protocol inheritance | It only moves where the error shows up. The default lives in a function, so nothing needs inheriting. |

## How to add a new source

Adding a source is five small steps: (1) a `SourceType` value and its `KIND_BY_SOURCE` entry in `domain/enums.py`; (2) a metadata model in the `SourceMetadata` union in `domain/metadata.py`; (3) a connector file with its input model in `connectors/`; (4) its entry in `CONNECTORS` (and `PULLERS` if it pulls) in `connectors/registry.py`; (5) fixtures under `tests/fixtures/<type>/`. The contract test fails until all five exist. Zendesk is the example below.

1. Add `SourceType.ZENDESK` and its entry in `KIND_BY_SOURCE`, both in `domain/enums.py`. Reuse an existing kind. (`custom` is the one type with no entry: its kind comes per record from `KIND_BY_RECORD_TYPE`.)
2. Add `ZendeskMetadata` (with `source_type: Literal[SourceType.ZENDESK]`) to `domain/metadata.py` and to the `SourceMetadata` union.
3. Write `connectors/zendesk.py` with a `ZendeskTicketIn` input model, `source_type`, `version`, `required_config` (empty unless it needs config), `external_event_id` (`f"{ticket id}:{updated_at}"`), `transform` built on `new_record`, and a `verify_signature` override for Zendesk's timestamp-plus-body scheme. Add `pull_config` and `pull` only if Zendesk will be polled.
4. Add `ZendeskConnector()` to the tuple inside `CONNECTORS`, and to `PULLERS` (via a typed local) if it pulls.
5. Put synthetic fixtures in `tests/fixtures/zendesk/`: `ticket.json`, `ticket_edited.json` (same id, later `updated_at`, so the contract test can prove an edit is a new event and the newer text wins) and `malformed.json`.

`tests/unit/connectors/test_registry.py` and `tests/unit/test_models.py::test_every_source_type_has_a_metadata_model` fail until all five steps are done. The contract tests in `tests/unit/connectors/test_contract.py` then run every fixture. Add one golden test for the source's odd cases. Catch to say out loud: `test_verify_signature_accepts_signed_body_and_rejects_tampered` in `test_contract.py` signs with the default `X-Signature` header, so a connector that overrides the signature needs that test taught its scheme. Run `uv run pytest tests/unit/connectors` until green.

Worked example: the custom connector (commit b8f6e2b) was added exactly this way: `SourceType.CUSTOM`, `CustomMetadata`, `connectors/custom.py`, one entry in the `CONNECTORS` tuple, and `tests/fixtures/custom/`.

No service, route, worker or table changes.

## How to say it in the interview

**One-minute pitch.**
"A Source is a tenant's configured instance. A connector is the code that translates for one source type. Every payload, webhook or poll, is stored raw first. A worker then asks the connector to turn it into zero or more feedback records. The connector checks the payload with a Pydantic model first, so a bad payload fails at one line and goes to the dead list, and nothing is lost. A dict maps each source type to its connector, so no other code knows which sources exist. Discourse's connector can also pull, page by page. Its cursor moves only once the whole search window is in. Signatures default to HMAC-SHA256, and a connector overrides that only when its source signs differently. Adding Zendesk is an enum value, a metadata model, one connector file, one registry entry and fixtures. The registry and metadata tests fail until all exist. The custom connector was added exactly this way."

**"Isn't this just a big if/else on source_type?"**
Yes, a dict is a dispatch table. The difference is where it lives. An if/else would be copied into the webhook, the worker and the poller. The dict is in one file, its keys are type-checked, and a test fails if a type is missing. Adding a source never edits the core.

**"Where does per-source signature verification go?"**
On the connector, as `verify_signature(secret, body, headers)`. The default, HMAC-SHA256 hex in `X-Signature`, is written once. Intercom would override it with SHA-1 in `X-Hub-Signature`. Discourse would strip `sha256=` from its own header. The algorithm belongs to the source type. The secret belongs to the tenant's Source row.

**"What if a source needs both push and pull?"**
Push or pull is an ingress choice, stored as `Source.mode`. Both paths write the same `raw_events` table, and the same transform reads it. Webhooks are push-only: a pull source answers 409 on the webhook route, and it cannot be created with a `webhook_secret` (422). Creating a pull Source for a type that cannot pull is rejected too. Letting one source take both is an extension, not built.

**"How do you version a transform?"**
Every record carries `connector_version`. Fix the transform, bump `version`, and replay the stored raw events for each affected source, with bulk replay (`POST /admin/raw-events/replay?source_id=...&status=processed`). Replay goes through the same `>=` version guard (ADR-002), so an equal version is accepted and the fixed output overwrites the record. Raw payloads are kept (as parsed JSON), so nothing is lost. The stronger version: run v2 over raw events next to v1, diff the results, then switch.

**"How do you test a connector?"**
Fixture in, expected record out, no mocks. One contract test runs every connector over every fixture. It checks that output is deterministic, identity and the version are stamped, the event id never raises and changes on an edit, a malformed payload raises `ValidationError` (which sends it dead in the worker), and the signature accepts a signed body and rejects a tampered one. Pull uses a stub HTTP client. A failure on page 2 must leave the stored cursor where it started.

**"How does a webhook find its tenant?"**
The URL is `/v1/sources/{source_id}/events`, with no API key, because a real sender cannot add ours. We look the source up by its unguessable id (404 if unknown), refuse a pull source (409), check the signature with that source's secret on the raw bytes before we write anything (401 if wrong), and take the tenant from the source row.

**"What if a source edits a post?"**
The edit has a new update time, so it gets a new raw-event id and is stored. The worker transforms it, and the upsert sees a newer timestamp and overwrites the record. The same post re-pulled without changes has the same id and is dropped. An older copy arriving late loses the timestamp check. A Twitter edit gets a new tweet id, so we key the record on the original tweet id.

**"What if a new kind of feedback shows up, like an NPS survey?"**
A new kind is an enum value plus optional fields in metadata. That needs no migration. If everyone needs to query the score, it becomes a common column, which means a migration and a replay. The record is the extension point that costs most. The connector is the cheap part.

## The one thing to do first

Write `tests/unit/connectors/test_contract.py` before any connector, and make it fail. It checks:
1. `set(SourceType) == CONNECTORS.keys()`, `PULLERS` is a subset of `CONNECTORS`, and every type has a fixture (built: in `test_registry.py`, with a `malformed` fixture per type);
2. for each connector and fixture: the transform is deterministic, `metadata.source_type` and `connector_version` match the connector, and `external_event_id` never raises;
3. **the edit case**: the same item with two update times gives two different event ids, both enqueue, and the record ends with the newer text;
4. a malformed fixture raises `ValidationError` (the worker then marks it dead);
5. `verify_signature` accepts a correctly signed body and rejects a tampered one.

Then build Playstore, the simplest connector, until the test goes green.
