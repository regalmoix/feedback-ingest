# Tailoring decisions (from public Enterpret research)

Sources: `01_product_and_integrations.md`, `02_engineering_and_stack.md`, `03_customers_and_use_cases.md`,
`04_ui_and_videos.md`. Everything below is based on public pages; exact figures are re-checked against the
linked pages before being quoted in the interview pack.

## What the research changed

Enterpret publishes a generic ingestion contract (`POST /webhook/custom/all`: a batch of records with `id`,
`type`, `createdAt` in epoch seconds and typed metadata; duplicate ids skipped by default; "accepted does not
mean processed"), and their engineering writing describes version-based rejection of stale updates,
per-tenant queue partitioning, noisy-neighbour incidents, and a ClickHouse analytics tier behind the
ingestion graph. Our design already mirrors the core of this (durable-before-ack with 202 meaning accepted,
a version guard on upsert, idempotent keys, replay from raw). The tailoring makes that visible and speaks
their vocabulary without pretending to copy their system.

## Adopted (built or written)

| # | Change | Why | Where |
|---|---|---|---|
| A1 | A fifth connector, `custom`, that accepts Enterpret's public webhook shape: `{"records": [{id, type, createdAt, text, title?, metadata{...}}]}` with `type` in `REVIEW, CONVERSATION, FORUM_CONVERSATION_THREAD, SURVEY`; one record per entry (our transform already returns a list); typed metadata validated as string/number/bool values; duplicates skipped per record id (our raw-event key); newer versions accepted | Proves extensibility on their own contract and that batch payloads fit the model; it is the "add Zendesk" demo done against something they recognise | `connectors/custom.py`, fixtures, registry, docs |
| A2 | `FeedbackKind.survey` added (with a `SurveyMetadata` model: score, question, response id) | Their `SURVEY` type needs a kind we did not have; it exercises the "new kind of feedback" extension path the council flagged as the costly one, so we can show it is one enum value and one metadata model | domain, metadata union, `KIND_BY_SOURCE` for custom (kind comes from the record's `type` for the custom connector, so `KIND_BY_SOURCE` gains a per-record override only for `custom`) |
| A3 | Demo story uses two synthetic tenants from the research: "Lumenote" (consumer voice app: Play Store reviews, Discourse community, custom survey webhook) and "Brightwave" (B2B SaaS: Intercom conversations, Twitter, custom webhook) | A realistic narrative mirrors their customer shapes (consumer app vs B2B SaaS) and the metadata questions their users ask (app version, country, plan) | `scripts/seed.py`, `demo.sh`, `demo_script.md` |
| A4 | Vocabulary in docs: "Feedback Record"; Unify → Understand → Act (we build Unify; taxonomy/Reasons/Wisdom are the Understand stage downstream of our records); "accepted does not mean processed"; version-based stale rejection; per-tenant partitioning as the noisy-neighbour upgrade; ClickHouse as the analytics tier; PII redaction before storage as the enrichment we did not build | Lets the candidate connect every design choice to how Enterpret describes its own system | README, whiteboard, qa_bank, extensions, glossary |
| A5 | New Q&A section "How this maps to Enterpret" (about ten questions) and one new slide "Where this sits in Enterpret's pipeline" | Shows the extra mile explicitly | `qa_bank.md`, `deck.pptx` |
| A6 | Failure-scenario rows reframed with their words where they fit: 4-hour polling cadence for support tools and app stores (ours is configurable, default 5 minutes), resolved-conversations-only ingestion for support tools, queue clogging and noisy neighbours (their named incidents) | Interviewers will recognise their own incident language | `failure_scenarios.md`, `firefight_runbook.md` |

## Rejected (said explicitly if asked)

- CSV / file import connector: out of scope for the assignment; it is the same transform behind a file reader.
- PII scrubber: real Enterpret redacts before storage; we only keep PII out of logs and error text. Listed as the first enrichment stage in `extensions.md`.
- Users and accounts as separate entities, workspace roles: beyond the assignment's tenant model; mentioned as the next layer.
- Replace-on-same-id toggle: we always accept a newer version and never an older one; their default (skip duplicates) is our raw-event behaviour, their opt-in (replace) is our upsert behaviour. Said as a comparison, not copied.
- Their request limits (200 KB, 100 records, 2000 req/min): we keep our 1 MiB body cap and no rate limit; rate limiting is in the debt ledger.
- Audio recordings: not a text source.

## Honesty rules

- Never claim knowledge of their internal implementation; cite only the public pages linked in the research notes.
- Say "their public docs describe" or "their engineering blog says", never "they do X internally".
- If a number cannot be re-verified on the linked page, do not quote it.
