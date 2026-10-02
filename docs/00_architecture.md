# Architecture

_v1, expanded in phase 6._

## In plain words

1. Customer feedback arrives from many places: some sources call us (push), others we go and fetch (pull).
2. Whatever arrives is first saved exactly as received, so nothing is lost even if later steps fail.
3. A background worker turns each saved item into one standard feedback record, whatever its source.
4. Each record has a fingerprint, so the same feedback arriving twice is stored only once.
5. Every customer (tenant) only ever sees their own data; broken items are parked and can be replayed.

## Diagram

```
                 push (webhook)                       pull (poll)
 Source ───► POST /v1/sources/{id}/events ──┐   Scheduler/`POST /sync` ──► Puller ──► Source API (httpx)
             (HMAC verify, tenant check)    │                                  │
                                            ▼                                  ▼
                                   IngestionService.accept(envelope)  ◄────────┘
                                            │  insert raw_events (status=pending)  → 202
                                            ▼
                                   Worker (asyncio loop, lease + retry/backoff)
                                            │  CONNECTORS[source.type].transform(raw) → FeedbackRecord
                                            ▼
                                   FeedbackRepository.upsert (UNIQUE dedupe_key)
                                            │
                                 raw_events.status = processed | failed(n) | dead (DLQ)
                                            │
                       GET /v1/records?source=&kind=&since=     POST /admin/raw-events/{id}/replay
```

## Domain model

- `Tenant(id, name, api_key_hash)`
- `Source(id, tenant_id, type: SourceType, name, mode: pull|push, config: dict, webhook_secret, cursor: dict|None)`
- `RawEvent(id, tenant_id, source_id, payload: dict, received_at, status: EventStatus, attempts, next_attempt_at, error)`
- `FeedbackRecord(id, tenant_id, source_id, source_type, external_id, dedupe_key, kind: FeedbackKind, title, text, author, language, rating, source_created_at, source_updated_at, ingested_at, metadata: dict)`
- Per-source metadata models: `DiscourseMetadata(topic_id, post_number, like_count, topic_title, url)`, `PlaystoreMetadata(app_version, device, country)`, `TwitterMetadata(country, retweets, handle)`, `IntercomMetadata(conversation_id, part_count, tags)`
- Enums: `SourceType{discourse,playstore,twitter,intercom}`, `FeedbackKind{review,conversation,post,tweet}`, `EventStatus{pending,processing,processed,failed,dead}`
