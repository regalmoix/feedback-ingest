# Council transcript 003: Connector abstraction

Date: 2026-10-03. Outcome: [ADR-003](ADR-003-connector-abstraction.md).

## 1. Framed question

DECISION: The shape of the "connector" abstraction, which is the extensibility story of a take-home backend assignment: "ingest feedback from heterogeneous sources (Intercom, Playstore, Twitter, Discourse), push (webhook) and pull (poll), multi-tenant, transform to a uniform internal record with per-source metadata; evaluation criteria: code quality, requirements covered, and extensibility, i.e. how easy it is to add a new type of feedback source." The candidate demos it on a whiteboard under deep cross-questioning and did not write the code, so the abstraction must be explainable in one minute and defensible in detail.

ALREADY DECIDED (fixed): Python 3.12, Pydantic v2, mypy --strict. A `Source` row = one configured instance per tenant (type, name, mode push|pull, config dict, webhook_secret, cursor). Every inbound payload (push or pull) is stored verbatim in a `raw_events` table (unique per source on an external event id or payload hash) and a worker later transforms it into a `FeedbackRecord` (unique per source on external_id, kind review|conversation|post, typed common columns + per-source metadata model in a discriminated union, connector_version stamped). Full-snapshot rule: a connector may only emit a complete record. Discourse is the only live pull source (search.json then t/{topic}/posts.json); Playstore, Twitter and Intercom are push sources fed from recorded fixture payloads. External interfaces (stores, queue, http, clock) are behind Protocol ports.

PROPOSED: one `Protocol` per capability plus a registry dict.
```python
class SourceConnector(Protocol):
    source_type: ClassVar[SourceType]
    version: ClassVar[int]
    def external_event_id(self, payload: dict[str, Any]) -> str | None: ...   # for raw_events uniqueness
    def transform(self, source: Source, payload: dict[str, Any]) -> FeedbackRecord: ...
class PullConnector(SourceConnector, Protocol):
    def pull(self, source: Source, http: HttpClient, now: datetime) -> tuple[list[dict[str, Any]], str | None]: ...  # payloads, new cursor
CONNECTORS: dict[SourceType, SourceConnector] = {SourceType.discourse: DiscourseConnector(), ...}
```
Webhook signature verification stays generic (HMAC-SHA256 over the body with the source's secret), not per connector. Adding a source = one connector file (~40–60 lines) + one metadata model + one registry entry + one fixture + the shared connector contract test passes.

ALTERNATIVES: (a) abstract base class with template methods (`_parse`, `_kind`, `_metadata`) and shared helpers; (b) config-driven declarative field mapping (JSON-path mapping per source, zero code for simple sources, code only for pull logic); (c) split roles: separate `Fetcher` (pull) and `Transformer` classes per source, registered separately; (d) per-source Pydantic input models (`PlaystoreReviewIn`) that validate the raw payload before a tiny mapping function, instead of dict-poking inside transform; (e) plugin discovery via entry points instead of a static dict.

STAKES: "How would you add Zendesk?" is a guaranteed question. So is "where does source-specific signature verification go?", "what if a source needs both push and pull?", "how do you version a transform?", "how do you test a connector?", and "isn't this just a big if/else on source_type?".

Fixed constraints from the project owner (not re-litigated): Protocol-based connector plus registry dict stays; Python 3.12, Pydantic v2, mypy --strict; no speculative abstractions (no Config models, no MappedConnector, no plugin discovery, no write-back or backfill capabilities; these may appear only as extensions); Playstore, Twitter and Intercom remain fixture-fed push sources for the demo, and the ADR must say plainly that real Play Store has no review webhook and Twitter needs a CRC handshake.

## 2. Advisor responses

### The Executor (Response A)
**Verdict: build it as proposed, with four changes, which adds about 2 hours of work.**
1. **Adopt (d) inside `transform`; it doesn't replace the design.** Under `mypy --strict`, indexing `payload["review"]["text"]` on a `dict[str, Any]` returns `Any`, so it passes the type check without actually checking anything. Start each connector with `PlaystoreReviewIn.model_validate(payload)`, then write a plain mapping. Malformed payloads then fail with a `ValidationError` at a clear point, and the worker marks that `raw_event` as failed. Derive `external_event_id` from the same model.
2. **Make classes inherit from the Protocol explicitly**, as in `class DiscourseConnector(PullConnector):`. mypy reports a missing `version` ClassVar at the class definition, not at the registry line. Protocol methods can carry default bodies. That gives `verify_signature(self, source, body: bytes, headers: Mapping[str, str]) -> bool` a place to live, defaulting to HMAC-SHA256. You need the override. Intercom signs with HMAC-SHA1 in `X-Hub-Signature`. Twitter uses base64 SHA256 and also needs a CRC GET challenge. Play delivers through Pub/Sub push with an OIDC JWT. "Generic HMAC" is wrong for most of the sources you actually have.
3. **Use two registries built from lists:** `CONNECTORS = {c.source_type: c for c in (Discourse(), Playstore(), ...)}` and `PULLERS: dict[SourceType, PullConnector]`. Keys derived from the ClassVar can't drift. No `@runtime_checkable`/`isinstance`. "Push and pull?" A pull connector already implements `transform`, so the webhook path works for it unchanged.
4. **Write the contract test before writing any connector.** Parametrize over `CONNECTORS.values()` crossed with `fixtures/{type}/*.json`. Assert: transform deterministic; `record.metadata.source_type == connector.source_type`; `external_event_id` stable; `set(SourceType) == CONNECTORS.keys()`.
**Order:** ports, contract test, Playstore (simplest), Discourse pull, Intercom. **Rejected:** (a) explicit Protocol inheritance gives the same defaults; (b) Discourse needs two HTTP calls per topic so JSON-path mapping grows into its own language; (c) twice the registration for no gain; (e) nobody installs third-party connectors. **Versioning:** bump `version`, re-run transform on raw_events joined to records where `connector_version < current`. **"Big if/else?"** No: a lookup on a type-checked key, with the contract test enforcing exhaustiveness.

### The Contrarian (Response B)
**The fatal flaw is the generic HMAC claim.** Intercom signs with `X-Hub-Signature` (HMAC-SHA1). Twitter/X requires a CRC challenge, a GET that must return an HMAC of a token. Discourse sends `X-Discourse-Event-Signature: sha256=...`. Play Store has no review webhook at all; reviews are pulled through the Reply to Reviews API. So the design has `PullConnector` but no `PushConnector`. Add `verify(headers, body, secret) -> bool` and an optional `handshake(request)` now. Stop calling Playstore a push source, or say up front you are faking it with fixtures.
**`transform -> FeedbackRecord` is the wrong cardinality.** Zero records (bot messages, admin replies, `conversation.deleted`, pings), many records (one Discourse topic payload holding N posts), or a tombstone (deleted tweet). Return `list[FeedbackRecord]`, or a small result type with skip and delete cases.
**Full snapshots plus upsert without ordering corrupts data.** Webhooks arrive out of order; you need `source_updated_at` and a last-write-wins guard on the upsert.
**`pull` returning `(list, cursor)` is all-or-nothing.** Rate-limited at topic 7 of 40 means you lose the batch or move the cursor past unfetched data. Yield pages, each with its own cursor.
**`dict[SourceType, SourceConnector]` loses the pull type.** Use separate `PULL` and `PUSH` registries plus a test that every `SourceType` is registered somewhere.
**`transform` receives the whole `Source`, including `webhook_secret` and `cursor`.** A transform should get `tenant_id` and `source_id`, nothing more.
Alternative (d), validating payloads with Pydantic input models, is not optional under mypy --strict.

### The Outsider (Response C)
**Your nouns overlap.** `Source`, `SourceType`, `SourceConnector` and "connector". Pick one sentence: "A Source is a tenant's configured instance. A connector is the code that translates for one source type."
**"Protocol" sounds like networking.** Say "a typing.Protocol, so connectors don't inherit anything." Be ready for "why not an ABC?": mypy --strict plus no shared base state.
**Mode is stored in two places.** `mode` on the Source row; whether a connector can pull on the class. What happens when a tenant sets Playstore to `mode=pull`? Something must reject that at configuration time. Name the check.
**Who actually pushes Playstore reviews to you?** Google Play has no review webhook; Twitter is mostly polled too. Say it plainly: "Fixtures stand in for a poller I didn't build. The same transform runs either way."
**"Generic HMAC" is the claim most likely to break.** Make verification an optional method with HMAC as the default.
**"Full-snapshot rule" and "connector_version stamped" are jargon until you show the payoff:** "Bump the version, replay raw_events, get new records."
**Drop "~40–60 lines."** You didn't write the code.
**The one-minute pitch:** "A connector turns a raw dict into a FeedbackRecord. Pull connectors can also fetch. A dict maps each source type to its connector, so there's no if/else. Adding Zendesk means one file, one dict entry, and the contract test passes."

### The First Principles Thinker (Response D)
The question is framed as "what shape is the connector?" That's the wrong question. `raw_events` stores every payload verbatim and a worker transforms later. That table is the real abstraction. It splits the system into two unrelated jobs: **Ingress** (how bytes get into raw_events: webhooks, polling, signatures, cursors, event identity) and **Transform** (a pure function `(Source, raw payload) -> FeedbackRecord`). A "connector" is mostly just the transform. Push vs pull isn't a kind of connector; it's `Source.mode`, which only picks the ingress path. "Both push and pull?" Both paths write the same raw table, the same transform reads it. `PullConnector(SourceConnector)` inheritance mixes the two jobs back together. Make pull a separate capability, not a subtype.
Two assumptions don't hold: **"Signature verification is generic HMAC" is false** (Intercom SHA-1 `X-Hub-Signature`, Twitter CRC challenge + base64 SHA-256, Zendesk signs timestamp+body). Make it optional `verify(headers, body, secret)` with HMAC default. **`external_event_id` is identity at ingress, not transform logic.**
Once raw is immutable and transform is pure: **Versioning** = bump `version` and replay. **Testing** = fixture in, golden record out, no mocks. **"Isn't this an if/else?"** Yes, a dict is a dispatch table; the goal is that the core never changes when a source is added.
Alternatives: **take (d)**; **reject (b)** (field mapping isn't the hard part; identity, threading and completeness are); **reject (e)**.
**Adding Zendesk:** input model, pure transform, metadata model, fixture, and `verify` if signing differs.

### The Expansionist (Response E)
The proposal is right. Keep Protocol plus registry, with three additions.
**1. Make (d) part of the contract.** Give each connector an `In` model for the payload and a `Config` model for the source config. `transform` is `In.model_validate(payload)` then a readable mapping. The input model documents the payload format, checks fixtures, and catches upstream schema drift (raw is kept, not lost). `Config` gives multi-tenant onboarding: export JSON schema, validate a new Source row on creation, a form for self-serve later.
**2. Make replay your answer on versioning.** Bump the version, re-run the worker over raw_events for that source type.
**3. Treat every capability as an optional protocol.** Push+pull is a class implementing both. Add an optional `WebhookVerifier` protocol with generic HMAC default; Intercom's SHA1 header and Twitter's CRC challenge become one-method overrides found with a `runtime_checkable` isinstance check.
**The registry is the test matrix.** Parametrize the shared contract test over `CONNECTORS.values()`. Declarative mapping (b) fits later as a `MappedConnector` satisfying the same Protocol.

## 3. Anonymisation mapping

A = The Executor, B = The Contrarian, C = The Outsider, D = The First Principles Thinker, E = The Expansionist

## 4. Peer reviews

### Review by The Contrarian
1. Strongest: B. Only response questioning the contract: wrong cardinality (zero/many/tombstone), out-of-order webhooks overwrite newer snapshots, all-or-nothing cursor loses or skips data. A close second (concrete, build order) but keeps the single-record return.
2. Biggest blind spot: C. Coaches presentation only; polishes a pitch that defends the same flaw B exposes; never answers how Zendesk is added, ordering, partial pulls, replay failures.
3. All missed: push sources may still need to fetch (if a webhook carries only a delta the push connector must call the API, putting HTTP and credentials inside a "pure" transform); webhook routing per tenant (how a request finds its Source and secret before verification; anti-spoofing); backfill for a newly configured push source.

### Review by The First Principles Thinker
1. Strongest: D. Asks what the system does before shaping the class: raw_events is the real abstraction, ingress vs pure transform; push/pull is Source.mode; versioning is replay; testing is fixture→golden; a dict is honestly a dispatch table; external_event_id belongs to ingress. B finds more defects, D gives the frame to fix them.
2. Biggest blind spot: E. "The proposal is right" plus surface area (Config models, MappedConnector, runtime_checkable isinstance) that weakens the mypy --strict story; misses B's cardinality, ordering, and that Play Store has no review webhook.
3. All missed: the extension point that will strain is FeedbackRecord, not the connector. A new kind of feedback (NPS survey with a score) breaks the review|conversation|post enum and common columns; "one file" doesn't survive that. Nobody said how an inbound webhook finds its tenant's Source (URL per source vs app-level Intercom webhook).

### Review by The Expansionist
1. Strongest: E. Treats the connector as something to build on: Config model per connector validates a Source row at creation, yields a JSON schema and a future self-serve form; keeps (b) open as a MappedConnector. A is the most complete hardening plan but only hardens.
2. Biggest blind spot: C. Coaches wording, changes nothing structural; misses cardinality and ordering; no upside beyond the pitch.
3. All missed: one-protocol-per-capability grows past ingest: a ReplyConnector (write-back), a Backfill capability for history import on first connect, and shadow-running a new connector version over raw_events (v1 vs v2 side by side, diff, then cut over) as the strongest answer to "how do you version a transform?"

### Review by The Outsider
1. Strongest: C. Only response dealing with the real constraint (whiteboard, didn't write the code): overlapping nouns, "Protocol" sounds like networking, jargon without payoff, drop the made-up line count, a sayable one-minute pitch. D close second: ingress vs transform is easy to follow.
2. Biggest blind spot: E. Adds Config models, MappedConnector, runtime_checkable isinstance; each makes the one-minute explanation harder; isinstance discovery is the if/else problem in another form; never questions Playstore as push.
3. All missed: how an inbound webhook finds its tenant (URL path like /webhooks/{source_id}?); the secret lookup before verification is where tenant isolation lives; nobody sketched request → raw_events → worker → FeedbackRecord end to end.

### Review by The Executor
1. Strongest: A. Only response you could build from as written: build order, every change checkable by mypy or a test, explicit Protocol inheritance surfaces a missing `version` at the class, list-built registry stops key drift, exhaustiveness test. Gap: cardinality (B caught it).
2. Biggest blind spot: E. Leaves real faults unchallenged (single-record transform, out-of-order overwrite, all-or-nothing pull); runtime_checkable isinstance only checks a method exists, undercutting mypy --strict.
3. All missed: THE DEDUP KEY WILL SILENTLY DROP UPDATES. If external_event_id for a pulled Discourse post is just the post id, an edited post pulled again collides on the raw_events unique key and is discarded, so its record never updates. Event identity must include updated_at or a revision. Nobody asked how an inbound webhook finds its tenant's Source before verification either.

## 5. Chairman synthesis

### Verdict

The proposed shape holds: a Protocol per capability plus a registry dict. It needed nine changes, and none of them adds a new layer:
1. `transform` returns a list (zero, one, many, or a tombstone);
2. the raw-event id includes the item's update time, so edits are not silently dropped;
3. signature verification becomes an optional per-connector method, with HMAC-SHA256 written once as the default;
4. `pull` yields pages, each with its own cursor;
5. two registries built from tuples, a completeness test, and a configuration-time mode check;
6. per-source Pydantic input models, with validation errors marked dead in one place;
7. `transform` gets the whole `Source`, with the secret typed as `SecretStr`;
8. one stated webhook path: URL, API key, tenant-scoped source lookup, signature, raw insert;
9. `FeedbackKind` is named as the honest limit.

The council's strongest inputs were these:
- the Contrarian's contract defects: cardinality, all-or-nothing pull, and a false generic-HMAC claim;
- the Executor's buildable plan and, in review, the dedup-key catch that would have dropped every edit silently;
- the First Principles framing that `raw_events` splits ingress from a pure transform. That framing is how the design is explained;
- the Outsider's plain-language pitch, the Playstore honesty, and the configuration-time check.

The Expansionist was named weakest by three of the five reviews. Its additions (Config models, MappedConnector, `isinstance` discovery) make the one-minute answer harder and weaken the mypy story. Only its shadow-run idea was kept, as an interview answer.

Two advisor claims were corrected: Play Store does not push reviews through Pub/Sub (Executor), and the out-of-order overwrite (Contrarian) was already handled by the upsert guard from ADR-002.

Weighting:
- Contrarian (correctness): high.
- Executor (buildability, dedup catch): high.
- First Principles (framing): high.
- Outsider (defensibility): medium. Used for wording and the configuration check.
- Expansionist (growth): low. Used for the extensions list and one interview answer.

The full decision follows. It is identical to ADR-003 from its Context section onward.

### Context

The brief scores extensibility as "how easy it is to add a new type of feedback source". The connector is our answer to that. It is also the part the interviewer will push on hardest.

A **connector** is the code for one source type. A **Source** is one tenant's configured instance of that type. Two Playstore apps for one tenant are two Source rows that share one connector.

The four sources, and what the real services do:

| Source | Mode in this project | What the real service does |
|---|---|---|
| Discourse | pull, live | We poll `search.json`, then `t/{topic}/posts.json`. Discourse also has webhooks, signed with `X-Discourse-Event-Signature: sha256=<hex>`. |
| Playstore | push, fed from fixture files | **Google Play has no review webhook.** Reviews are read by polling the Reply to Reviews API. Fixtures stand in for that poller. |
| Twitter | push, fed from fixture files | **Twitter webhooks need a CRC handshake first**: a GET we must answer with an HMAC of a token. Fixtures stand in for a poller. |
| Intercom | push, fed from fixture files | Real webhooks, signed with HMAC-SHA1 in `X-Hub-Signature: sha1=<hex>`. |

Our replay script posts the fixtures to our own webhook URL and signs them with our default scheme. The transform is the same code whichever way a payload arrives.

Already fixed before this review:
- Python 3.12, Pydantic v2, `mypy --strict`, no speculative abstractions.
- A `typing.Protocol` per capability plus a registry dict. This is the extensibility story and it stays.
- Every inbound payload, push or pull, is stored as-is in `raw_events` first. A worker transforms it later (ADR-001).
- `raw_events` is unique on `(source_id, external_event_id)`. `FeedbackRecord` is unique on `(source_id, external_id)` and has `deleted_at`, `connector_version` and `source_updated_at` (ADR-002).
- `FeedbackStore.upsert` only overwrites when `COALESCE(source_updated_at, source_created_at)` is newer or equal. So out-of-order webhooks cannot overwrite a newer record.
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

### Decision

#### The contract (`feedback_ingest/connectors/base.py`)

```python
from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel, ConfigDict

from feedback_ingest.domain.enums import SourceType
from feedback_ingest.domain.models import FeedbackRecord, Source
from feedback_ingest.ports.http import HttpClient
from feedback_ingest.utils import signing


class PullPage(BaseModel):
    model_config = ConfigDict(frozen=True)
    payloads: list[dict[str, Any]]
    cursor: str  # saved only after this page's raw rows are committed


def default_verify_signature(secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
    """HMAC-SHA256, hex, over the raw body, in header X-Signature. Written once, here."""
    return signing.verify(secret, body, headers.get("X-Signature", ""))


class SourceConnector(Protocol):
    source_type: ClassVar[SourceType]
    version: ClassVar[int]  # bump when transform output changes; stamped on every record

    def external_event_id(self, payload: dict[str, Any]) -> str: ...
    def transform(self, source: Source, payload: dict[str, Any]) -> list[FeedbackRecord]: ...
    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool: ...


class PullConnector(SourceConnector, Protocol):
    def pull(self, source: Source, http: HttpClient, now: datetime) -> Iterator[PullPage]: ...
```

A connector that uses the default signature delegates to it in two lines:

```python
    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
        return default_verify_signature(secret, body, headers)
```

#### The two registries (`feedback_ingest/connectors/registry.py`)

```python
_DISCOURSE = DiscourseConnector()
_ALL: tuple[SourceConnector, ...] = (_DISCOURSE, PlaystoreConnector(), TwitterConnector(), IntercomConnector())
_PULL: tuple[PullConnector, ...] = (_DISCOURSE,)

CONNECTORS: dict[SourceType, SourceConnector] = {c.source_type: c for c in _ALL}
PULLERS: dict[SourceType, PullConnector] = {c.source_type: c for c in _PULL}
```

The keys come from each connector's own `source_type`, so a key cannot drift from its value. mypy checks each object against the Protocol at the tuple annotation. A missing method or a missing `version` is a type error on that line.

Configuration-time check, run when a Source is created (the API turns it into a 422):

```python
def check_source(source: Source) -> None:
    if source.mode is SourceMode.PULL and source.type not in PULLERS:
        raise ValueError(f"{source.type} cannot pull")
    if source.mode is SourceMode.PUSH and source.webhook_secret is None:
        raise ValueError("a push source needs a webhook_secret")
```

#### The nine rulings

1. **Transform cardinality: `transform(source, payload) -> list[FeedbackRecord]`.** It returns 0 to N records. A ping, bot message or non-feedback event is an empty list, and the worker marks it processed. A deletion is a full record with `deleted_at` set, and the store never clears `deleted_at` (ADR-002). One payload holding several items returns several records. We do not add a result type, because a list already covers skip, one, many and delete.

2. **Raw-event identity: `external_event_id = f"{item id}:{updated_at or created_at}"` when the payload has them, else `payload_hash(payload)`.**
   - Why: `raw_events` drops any second insert with the same key. If the key were the bare post id, an edited Discourse post pulled again would collide with the first pull's row. It would be dropped silently, the worker would never see the edit, and the record would never update.
   - With the timestamp in the key, an edit is a new raw event. An unchanged post re-pulled in the overlap window has the same key and is dropped, which is what we want.
   - `external_event_id` runs at ingress on a payload nobody has validated yet. It must never raise. If either field is missing it returns the payload hash. A malformed payload is still stored, then goes dead in the worker with a clear error.
   - `external_id` (record identity) stays the bare item id. Twitter's stays the original tweet id (ADR-002).

3. **Signature verification: an optional per-connector `verify_signature(secret, body, headers) -> bool`.** The default is HMAC-SHA256, hex, over the raw body, in header `X-Signature`. It is written once, as `default_verify_signature`, and each connector delegates to it unless its source signs differently. None of the four connectors override it in this project, because the replay script signs fixtures with the default. The hook is where real schemes go:
   - **Intercom**: compute HMAC-SHA1 over the body, read `X-Hub-Signature`, strip `sha1=`, compare with `hmac.compare_digest`.
   - **Discourse webhooks**: read `X-Discourse-Event-Signature`, strip `sha256=`, then compare as the default does.
   - **Zendesk**: HMAC-SHA256 over the timestamp header plus the body, base64, in `X-Zendesk-Webhook-Signature`.
   - **Twitter's CRC handshake** is a GET challenge, not a signature check. It is an extension (a `handshake` method), added only if Twitter becomes a real webhook.
   - The algorithm belongs to the source type, so it lives on the connector. The secret belongs to the tenant's instance, so it lives on the Source row.

4. **Pull shape: `pull(source, http, now) -> Iterator[PullPage]`, where `PullPage(payloads, cursor)`.**
   - The poll service enqueues one page's payloads and commits them. Only then does it save `page.cursor`.
   - If the HTTP port raises `TransientError` on page 7 of 40, pages 1 to 6 and their cursor are already saved. The next poll resumes from there.
   - If the process crashes between the commit and the cursor save, the page is fetched again. Rule 2 drops the repeats.
   - A page's cursor must be safe to resume from: everything older than it is in this page or an earlier one. With oldest-first pages, that is the page's newest timestamp minus a small overlap. If a source only sorts newest-first, the connector holds the cursor back and yields it on the final page.

5. **Registries: `CONNECTORS` and `PULLERS`, built from tuples of instances, as above.** A test asserts `set(SourceType) == CONNECTORS.keys()`, that no two connectors claim one type, that `PULLERS.keys() <= CONNECTORS.keys()`, and that every type has at least one fixture. `check_source` rejects a pull-mode Source whose type has no puller. There is no `isinstance` discovery.

6. **Input models: every connector validates first.** `transform` starts with `PlaystoreReviewIn.model_validate(payload)` (or `DiscoursePostIn`, `TweetIn`, `IntercomEventIn`), then maps plain typed fields. Input models use `extra="ignore"`. Why: under `mypy --strict`, `payload["review"]["text"]` is `Any`, so it passes the type check without checking anything. A `ValidationError` is a permanent failure. The worker catches `ValidationError` next to `PermanentError` and marks the event dead. That is one `except` clause in the worker, not one per connector, and it also catches a bad `FeedbackRecord` or metadata model.

7. **What `transform` receives: the whole `Source`, with `webhook_secret: SecretStr | None`.** The risk is a log line or exception message that prints a Source and leaks the secret. A slimmer `SourceRef` model would protect only the transform. `SecretStr` prints `**********` everywhere: logs, `repr`, the API. It is a one-word type change and adds no model. The router calls `get_secret_value()` once, to verify. The SQL store must write `get_secret_value()` too, because `model_dump(mode="json")` would store the asterisks. A round-trip test covers that. A transform reads only `tenant_id`, `id` and `config`. It never reads `cursor`.

8. **Webhook routing, end to end:**
   1. `POST /v1/sources/{source_id}/events` arrives with `X-API-Key`.
   2. We hash the key and call `TenantStore.get_by_api_key_hash`. No tenant gives 401.
   3. `SourceStore.get(source_id, tenant.id)`. A source owned by another tenant looks exactly like a missing one: 404. A source in pull mode gives 409.
   4. `CONNECTORS[source.type].verify_signature(secret, raw_body_bytes, headers)` runs on the raw bytes, before JSON parsing. A failure gives 401.
   5. We parse the JSON, compute `external_event_id`, and call `RawEventQueue.enqueue`. New or duplicate, the reply is 202.
   6. Later, the worker claims the row, loads the Source, calls `transform`, upserts each record, and marks the event processed. A `ValidationError` or `PermanentError` marks it dead. A `TransientError` marks it failed and schedules a retry.
   - Tenant isolation happens in step 3: the secret used in step 4 belongs to a source this tenant owns.

9. **Known limit: `FeedbackKind` is where the design strains.** An NPS survey with a 0–10 score does not fit `review | conversation | post`. The answer: "a new kind is an enum value plus optional fields in metadata; the record is the extension point that costs most". Adding the enum value needs no migration, because `kind` is stored as text. The real cost comes when the new kind needs a field everyone queries, like an NPS score. That field becomes a new common column, which means a migration plus a replay. That cost is in the record, not in the connector.

#### Small consequences for the Phase 1 models

- `Source.webhook_secret` becomes `SecretStr | None` (ruling 7).
- `transform` stays free of clocks and random ids, so the same input always gives the same output. The worker stamps `id` and `ingested_at` with `model_copy(update=...)`. The contract test compares records with those two fields excluded.

### Where the council agrees

- Keep the Protocol plus registry dict. The dict is a dispatch table, and that is the honest answer to "isn't this an if/else?" (Executor, Outsider, First Principles, Expansionist).
- "Generic HMAC for all sources" is false. Make verification an optional method with an HMAC default (all five).
- Adopt alternative (d), per-source input models, inside `transform` (Executor, Contrarian, First Principles, Expansionist).
- Versioning means: bump `version`, then replay `raw_events` (Executor, Outsider, First Principles, Expansionist).
- Test with one shared contract test run over the registry and the fixtures. No mocks (Executor, First Principles, Expansionist).
- Reject plugin discovery (e) and declarative mapping (b) for now (Executor, First Principles; the Expansionist would keep (b) for later).
- Say plainly that Play Store has no review webhook and fixtures stand in (Contrarian, Outsider).
- Out-of-order webhooks need a last-write-wins guard (Contrarian). It already exists in `FeedbackStore.upsert` (ADR-002).

### Where the council clashes

1. **One record or a list?** The proposal, Executor and Expansionist return one record. The Contrarian says zero, many or a tombstone. **Ruling: a list** (ruling 1). A payload that is not feedback has no honest single-record answer.
2. **Is pull a subtype or a separate job?** First Principles says `PullConnector(SourceConnector)` mixes ingress back into transform. The Executor keeps the subtype. **Ruling: keep the subtype, use the First Principles framing to explain it.** Every puller must transform what it fetches, so the two belong in one class. Push or pull is still chosen by `Source.mode`. `PULLERS` keeps the type information, and `check_source` keeps mode and capability in step.
3. **Inherit from the Protocol explicitly?** The Executor wants explicit inheritance, so errors show up at the class and a default method can live on the Protocol. The Outsider wants to be able to say "connectors inherit nothing". **Ruling: structural, no inheritance.** mypy still catches a broken connector at the registry tuple. The signature default is a module function that connectors call, so nothing needs inheriting.
4. **`runtime_checkable` + `isinstance` (Expansionist) or static registries (Executor)?** **Ruling: static.** `isinstance` on a Protocol only checks that method names exist, not their signatures. It is weaker than mypy, and it is just the if/else in another form.
5. **Grow the abstraction or keep it small?** The Expansionist wants Config models and a MappedConnector. The Executor, Outsider and First Principles want it small. **Ruling: small.** `config: dict[str, str]` plus `check_source` covers four sources. Everything else is listed as an extension.
6. **Does transform get the whole Source?** The Contrarian says give it only `tenant_id` and `source_id`. **Ruling: whole Source, with `SecretStr`** (ruling 7). That fixes the leak everywhere, not only in the transform.
7. **Is `external_event_id` connector logic or ingress logic?** First Principles says it is identity at ingress. **Ruling: both are right.** It stays on the connector, because only the connector knows where the id is in the payload. It runs at ingress, must never raise, and includes the timestamp (ruling 2).
8. **Does Play push reviews?** The Executor said Play delivers through Pub/Sub push with an OIDC token. The Contrarian said Play has no review webhook. **Ruling: the Contrarian is right.** Play's Pub/Sub notifications cover purchases and subscriptions, not reviews.
9. **Add `handshake()` now (Contrarian)?** **Ruling: no.** No source in this project has a live webhook that needs one. It is named as an extension.

### Blind spots the council caught

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
- Real third-party senders (Intercom, Zendesk) cannot add our `X-API-Key` header. Our replay script sends it. For a real sender, the unguessable `source_id` in the path plus that source's signature authenticate the call, and the tenant comes from the source row.

### Rejected alternatives and why

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

### How to add a new source

Adding Zendesk is one file plus one metadata model plus one registry entry plus one fixture; the contract test fails until all are done.

1. Add `SourceType.ZENDESK`. The completeness test fails right away.
2. Add `ZendeskMetadata` (with `source_type: Literal["zendesk"]`) to `domain/metadata.py` and to the `SourceMetadata` union.
3. Write `connectors/zendesk.py` with a `ZendeskTicketIn` input model, `external_event_id` (`f"{ticket id}:{updated_at}"`), `transform`, and a `verify_signature` override for Zendesk's timestamp-plus-body scheme. Add `pull` only if Zendesk will be polled.
4. Add `ZendeskConnector()` to `_ALL`, and to `_PULL` if it pulls.
5. Put a recorded, synthetic payload in `tests/fixtures/zendesk/`, plus a malformed one. Run the contract test, and add one golden test for Zendesk's odd cases.

No service, route, worker or table changes.

### How to say it in the interview

**One-minute pitch.**
"A Source is a tenant's configured instance. A connector is the code that translates for one source type. Every payload, webhook or poll, is stored raw first. A worker then asks the connector to turn it into zero or more feedback records. The connector checks the payload with a Pydantic model first, so a bad payload fails at one line and goes to the dead list, and nothing is lost. A dict maps each source type to its connector, so no other code knows which sources exist. Discourse's connector can also pull, page by page, and each page carries its own cursor. Signatures default to HMAC-SHA256, and a connector overrides that only when its source signs differently. Adding Zendesk is one file, one metadata model, one dict entry and one fixture. The contract test fails until all four exist."

**"Isn't this just a big if/else on source_type?"**
Yes, a dict is a dispatch table. The difference is where it lives. An if/else would be copied into the webhook, the worker and the poller. The dict is in one file, its keys are type-checked, and a test fails if a type is missing. Adding a source never edits the core.

**"Where does per-source signature verification go?"**
On the connector, as `verify_signature(secret, body, headers)`. The default, HMAC-SHA256 hex in `X-Signature`, is written once. Intercom would override it with SHA-1 in `X-Hub-Signature`. Discourse would strip `sha256=` from its own header. The algorithm belongs to the source type. The secret belongs to the tenant's Source row.

**"What if a source needs both push and pull?"**
Push or pull is an ingress choice, stored as `Source.mode`. Both paths write the same `raw_events` table, and the same transform reads it. A pull connector is also a normal connector, so its webhooks work unchanged. Creating a pull Source for a type that cannot pull is rejected. A contract test checks that a webhook and a poll give the same `external_id` for the same item.

**"How do you version a transform?"**
Every record carries `connector_version`. Fix the transform, bump `version`, and replay the stored raw events for that source type. Replay skips the timestamp guard on purpose (ADR-002). Raw payloads are kept as-is, so nothing is lost. The stronger version: run v2 over raw events next to v1, diff the results, then switch.

**"How do you test a connector?"**
Fixture in, expected record out, no mocks. One contract test runs every connector over every fixture. It checks that output is deterministic, types match, the version is stamped, the event id is stable and changes on an edit, a malformed payload goes dead, and the signature accepts a signed body and rejects a tampered one. Pull uses a stub HTTP client. A failure on page 2 must leave page 1's cursor saved.

**"How does a webhook find its tenant?"**
The URL is `/v1/sources/{source_id}/events`. The API key gives the tenant. We look up the source by id and tenant together, so another tenant's source looks missing (404). Then we check the signature with that source's secret, on the raw bytes, before we write anything.

**"What if a source edits a post?"**
The edit has a new update time, so it gets a new raw-event id and is stored. The worker transforms it, and the upsert sees a newer timestamp and overwrites the record. The same post re-pulled without changes has the same id and is dropped. An older copy arriving late loses the timestamp check. A Twitter edit gets a new tweet id, so we key the record on the original tweet id.

**"What if a new kind of feedback shows up, like an NPS survey?"**
A new kind is an enum value plus optional fields in metadata. That needs no migration. If everyone needs to query the score, it becomes a common column, which means a migration and a replay. The record is the extension point that costs most. The connector is the cheap part.

### The one thing to do first

Write `tests/unit/connectors/test_contract.py` before any connector, and make it fail. It checks:
1. `set(SourceType) == CONNECTORS.keys()`, no duplicate types, `PULLERS` is a subset of `CONNECTORS`, and every type has a fixture;
2. for each connector and fixture: the transform is deterministic, `metadata.source_type` and `connector_version` match the connector, and `external_event_id` never raises;
3. **the edit case**: the same item with two update times gives two different event ids, both enqueue, and the record ends with the newer text;
4. a malformed fixture ends dead with a `ValidationError` message;
5. `verify_signature` accepts a correctly signed body and rejects a tampered one.

Then build Playstore, the simplest connector, until the test goes green.
