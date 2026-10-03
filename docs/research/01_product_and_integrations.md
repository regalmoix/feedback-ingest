# Enterpret: product and integrations research

Method: public web only (enterpret.com, helpcenter.enterpret.com). Page contents were read through a summarising fetch tool, so exact field names and numbers should be re-checked against the linked page before being quoted. Items tagged **[inference]** are mine, not Enterpret's claims. Items tagged **[not documented]** were looked for and not found.

## 1. What the product does end to end

- Positioning: "customer intelligence" platform that unifies feedback from support, sales calls, surveys, reviews, social, CRM and product usage, then structures it and pushes it to workflows. Home page flow is **Unify -> Understand -> Act**. https://www.enterpret.com/
- Pipeline in their words:
  - Ingest: 50+ native connectors, plus webhook, data-warehouse sync and file upload. https://www.enterpret.com/platform/feedback-integration
  - Unify/standardise: "unifies and standardizes fields, preserves metadata" at ingestion. Same page.
  - Classify on arrival: "Every feedback is classified in your taxonomy the moment it lands - zero manual tagging". Same page.
  - Context: a **Customer Knowledge Graph / Customer Context Graph** links feedback to users, accounts, opportunities, products, segments, ARR. https://www.enterpret.com/changelog/october-2025-product-highlights
  - Insight: **Wisdom** AI answers plain-English questions over 100% of the corpus with citations; search, dashboards, reports, anomaly detection. Same changelog; https://helpcenter.enterpret.com/en/articles/14403012-enterpret-wisdom-for-slack
  - Act: Slack and email delivery, Jira and Linear ticket creation, Salesforce, and an MCP server so Claude/ChatGPT/Cursor can query the data. https://www.enterpret.com/ and https://www.enterpret.com/blog/model-context-protocol-mcp-server-native-integrations-claude-notion-glean-chatgpt
- Reports and alerts: Feed Reports, Dashboard Reports, Search Reports, Feedback Stream, Quantify / Compare / Anomalies reports; delivery by email or Slack in real time, daily, weekly or monthly. https://helpcenter.enterpret.com/en/articles/8116431 and https://www.enterpret.com/changelog/subscribe-share-insights-on-slack-seamlessly
- Health monitoring on connectors: automated periodic checks every 3 hours with proactive alerts. https://www.enterpret.com/platform/feedback-integration
- Scale reference: Canva cited at 220M+ feedback records analysed. https://www.enterpret.com/

## 2. Integrations / feedback sources

Terminology: "Feedback sources, also called **Integrations** in Enterpret". https://helpcenter.enterpret.com/en/articles/6446339-what-are-feedback-sources

Catalogue (category as shown on https://www.enterpret.com/integrations):

| Category | Names |
|---|---|
| Customer support | Zendesk (Support and Chat), Intercom, Front, HubSpot, Freshchat, Kustomer, LiveChat, Zoho Desk, Salesforce Service Cloud, Pylon, Decagon |
| Reviews | Apple iOS App Store, Google Play Store, G2, Trustpilot, Google My Business |
| Survey | Typeform, SurveyMonkey, Qualtrics, Delighted, Medallia Agent Connect, Refiner, Sprig |
| Community | Discourse, Discord, Slack, Facebook Groups, Gainsight |
| Social | Facebook, Instagram, TikTok, YouTube Comments (older help-center list also has Reddit, Twitter) |
| Call recordings | Gong, Chorus, Fathom, Grain, AWS Connect, Zoom, Email ingestion |
| CRM / generic | Salesforce Sales Cloud, HubSpot, Zapier, Webhook, CSV Upload |
| Data warehouse | Snowflake, Census |
| Product analytics | Amplitude, Mixpanel, Segment |
| Actions / AI | Jira, Linear, Slack, Notion, Claude, ChatGPT, Cursor, Glean, n8n |

Push vs pull vs file, as documented (many articles are silent, flagged **[not documented]**):

| Source | Mode | Evidence |
|---|---|---|
| Custom Webhook | **Push** (HTTP POST, `api-key` header) | https://helpcenter.enterpret.com/en/articles/12131693-webhook-integration |
| CSV / File Upload | **File** (CSV only; Excel must be exported to CSV; processing can take up to 24h) | https://helpcenter.enterpret.com/en/articles/6556132-file-upload-csv-data-on-enterpret |
| Intercom | **Pull**, OAuth, every 4h, resolved conversations only, ~30-40 min per 10k tickets on backfill | https://helpcenter.enterpret.com/en/articles/6320475-intercom |
| Front | **Pull**, API token, every 4h, resolved only, 3-4h per 10k tickets backfill | https://helpcenter.enterpret.com/en/articles/6320539-front |
| Apple App Store | **Pull**, public API by AppID, every 4h, first 10k reviews in 15-20 min; optional App Store Connect keys (Key ID, private key, Issuer ID) for richer metadata | https://helpcenter.enterpret.com/en/articles/6331603-apple-app-store |
| Google Play | **Pull**, AppID, every 4h, first 10k in 5-10 min; optional service-account JSON for richer metadata | https://helpcenter.enterpret.com/en/articles/6331595-google-play-store |
| Typeform | OAuth 2.0 plus Typeform webhook API; "every 24 hours" | https://helpcenter.enterpret.com/en/articles/6331504-typeform |
| Salesforce | **Pull**, OAuth, continuous; objects Case, Opportunity, Lead, Task, Event, Survey Response, custom; one object per integration; admin picks which fields hold customer language and whether the type is Conversation or Survey | https://helpcenter.enterpret.com/en/articles/6453764-salesforce |
| Snowflake | **Pull** (Enterpret reads your DB), RSA key-pair auth, high-watermark on `ERC_ROW_CREATED_AT`, initial pull up to 24h | https://helpcenter.enterpret.com/en/articles/6601122-snowflake |
| Slack | Bot added to selected channels; messages ingested as feedback; frequency **[not documented]** | https://helpcenter.enterpret.com/en/articles/7019865-slack |
| Discourse | Admin pastes forum URL plus category links; picks a feedback template; pull method and cadence **[not documented]**; unit is the thread | https://helpcenter.enterpret.com/en/articles/8228431-discourse-integration |
| Zendesk, Gong, G2, Reddit etc. | Native connectors; specifics not retrieved | https://helpcenter.enterpret.com/en/articles/8999488-integration-descriptions |

- Typical connection UX: OAuth "in under 60 seconds"; only org admins can enable or modify connectors. https://www.enterpret.com/platform/feedback-integration
- Backfill: historical data is ingested on first connect and themed with the same taxonomy. https://www.enterpret.com/guides/data-ingestion-checklist-7-questions-to-ask-every-feedback-vendor
- Sources without native links (File Upload, Webhook, Snowflake) let an admin designate one metadata field as the clickable "source link". https://helpcenter.enterpret.com/en/articles/6693183-view-manage-metadata

## 3. How a feedback record is modelled

Enterpret-side vocabulary: **Feedback Record** ("FeedbackRecord" in the export API; "ERC" prefix in the Snowflake schema), grouped by **source** and **type**.

Webhook ingest shape (https://helpcenter.enterpret.com/en/articles/12131693-webhook-integration):
- Envelope: `{ "records": [ ... ] }`, up to 100 records per batch recommended.
- Universal fields: `id` (unique), `fileID` (source identifier), `type`, `createdAt`, `metadata`. All five required.
- `type` is one of `REVIEW`, `SURVEY`, `CONVERSATION`, `FORUM_CONVERSATION_THREAD`, `AUDIO_RECORDING`.
  - REVIEW: non-empty `text`.
  - SURVEY: `surveyResponse.responses[]`, each with `question`, `answer` (string or array), `selectedOptions`; a question is required if an answer or option is present.
  - CONVERSATION: `conversation.msgs[]`, at least one message, each with `actor` in {`user`, `agent`, `bot`} and non-empty `text`.
  - FORUM_CONVERSATION_THREAD: same as conversation; first message is the original post, later messages are replies.
  - AUDIO_RECORDING: `audioRecording.audioURL` (public, must respond 2xx within 10s) with optional `transcript`; formats mp3, mp4, wav, flac, ogg, amr, webm, m4a.
- `createdAt`: Unix epoch **seconds**; must be >= 2000-01-01 and not in the future; 13-digit values are auto-converted to seconds.
- `metadata`: nested typed arrays, type tags `s` (string), `n` (number), `b` (boolean); one type per field, no mixing. Example from docs: `"rating": { "array": { "n": [5] } }`.
- Guidance: put the actual feedback in content fields (`text`, `conversation.msgs[].text`, `surveyResponse.responses[].answer`) and context (rating, tier, demographics) in metadata. Same page.
- Metadata examples named in the docs: app store version and rating, survey title and rating, CRM plan type and tags, chat channel (https://helpcenter.enterpret.com/en/articles/6693183-view-manage-metadata); NPS/CSAT score and tags in CSV (https://www.enterpret.com/changelog/introducing-csv-upload). App version, country and plan are **[inference]** from these examples, not a fixed field list.

Metadata handling in the product (https://helpcenter.enterpret.com/en/articles/6693183-view-manage-metadata):
- Types string / number / boolean; admins can rename, describe, hide, and star up to 2 fields per source.
- Each field shows unique-value count and coverage percentage.

Stored/exported record (Export API v1, https://helpcenter.enterpret.com/en/articles/9618433-data-export-api):
- Fields: `id`, `source`, `orgID`, `type` (`RecordTypeReview`, Conversation, Survey, ForumThread), `sourceTimestamp`, `ingestedAt`, `languages` (ISO 639-3), `predictions[]` (`labelID` plus sentiment / reason / aspect, with confidence), `summary`, content variants with English copies (`text`/`textEn`, `conversation`/`conversationEn`, `survey`/`surveyResponseEn`), and `metadata`.
- Labels resolved via `/export/external/v1/labels/<labelid>` with `displayName`, `type` (REASON / ASPECT / SENTIMENT), `description`.
- Timestamps: record timestamp is immutable after first ingest; a different timestamp on a re-sent id is ignored; fixing needs delete and resend. https://helpcenter.enterpret.com/en/articles/14088289-feedback-record-timestamp-handling

Snowflake record columns (https://helpcenter.enterpret.com/en/articles/6601122-snowflake): `ERC_ID` VARCHAR(40), `ERC_CREATED_AT`, `ERC_ROW_CREATED_AT`, and exactly one of `ERC_TICKET_DATA` (object), `ERC_SURVEY_DATA` (object), `ERC_REVIEW` (text); extra columns such as `USER_PLAN`, `TAGS`, `ACCOUNT_TIER` become metadata.

Users and accounts (https://helpcenter.enterpret.com/en/articles/8611269-syncing-users-and-accounts):
- Separate entities: `POST https://api.enterpret.com/webhook/users/custom` with `users[]` (`id`, `attributes`, `createdAt`) and `POST .../webhook/accounts/custom` with `accounts[]` (e.g. `planType`, `ARR` attributes). Max 15 per request; separate API token per integration.
- Linked to feedback through a shared identifier such as user email or user id in feedback metadata.

## 4. Multi-tenancy / workspace / team concepts

- "Workspace" is the tenant container (Workspace Settings; "your Enterpret instance"). https://helpcenter.enterpret.com/en/articles/8105537-what-is-user-management-in-enterpret
- Roles: Admin (integrations, data flow, users; includes editor rights), Editor (taxonomy and metadata), Member (consumes insights, creates artefacts, subscribes to reports), Viewer (read-only). Same page.
- Auto-approve by company email domain; SSO via Okta and Azure AD SAML. Same page.
- API objects carry `orgID`; the Knowledge Graph is "extensible with each tenant potentially having additional tenant-specific objects". https://helpcenter.enterpret.com/en/articles/13452140
- Each webhook integration has its own API key, and each integration is created by an admin per source (and per type: Feedback / User / Account). https://helpcenter.enterpret.com/en/articles/12131693-webhook-integration
- Teams as a first-class entity: **[not documented]** in what I fetched; the taxonomy page mentions mapping context to team ownership. https://www.enterpret.com/platform/adaptive-taxonomy
- No user-count limit on plans. https://toolradar.com/tools/enterpret/pricing (third party)

## 5. De-duplication, language, translation, PII

- Dedup:
  - Webhook: record `id` is the key. Mutability is **off by default**; when enabled (via support), a repeated `id` **replaces** the record (no merge). https://helpcenter.enterpret.com/en/articles/12131693-webhook-integration
  - Polling connectors (Intercom, Front): if a conversation gets a reply outside the 4h window the whole conversation is re-ingested, "multiple copies may appear", but they say "it does not affect your data count during analysis". https://helpcenter.enterpret.com/en/articles/6320475-intercom
  - Snowflake: set `ERC_ROW_CREATED_AT` to now with the same `ERC_ID` to force re-ingest. https://helpcenter.enterpret.com/en/articles/6601122-snowflake
  - Mutable Records: standard behaviour ingests a ticket once, on close; the option ingests on creation and again on close, at extra cost. https://helpcenter.enterpret.com/en/articles/9019938-mutable-records
  - Content-level dedup (near-duplicate text): **[not documented]**. They do dedupe taxonomy Reasons ("Smart Keywords and Reason Deduplication"), which is a different thing. https://www.enterpret.com/blog/enterpret-taxonomy-revolutionizing-the-way-companies-use-customer-feedback
- Language: "works with 70+ languages" on most connector pages; records carry detected `languages` as ISO 639-3. https://www.enterpret.com/integrations/webhook and https://helpcenter.enterpret.com/en/articles/9618433-data-export-api
- Translation: reviews are auto-translated to English (exported as `textEn`, `conversationEn`). https://helpcenter.enterpret.com/en/articles/9618433-data-export-api. The App Store / Play Store search summary also said translation, but the help-center page itself did not mention it.
- PII: automatic detection and obfuscation "before ingestion" (e.g. SSNs, credit cards), plus tenant-specific custom scrubbers; example redaction `[NAME]`, `[EMAIL]`; scrubbed at the ingestion layer so raw PII never lands in the analysis store. https://www.enterpret.com/platform/feedback-integration and https://www.enterpret.com/guides/how-to-detect-and-redact-pii-in-customer-feedback-2026
- Compliance claims: SOC 2 Type 2, GDPR, CCPA; ISO 27001 / 42001 / 27701 alignment. https://www.enterpret.com/guides/security-certifications-to-require-from-a-customer-feedback-vendor-before-you-sign

## 6. Public API / webhook docs

- Webhook ingestion (the closest analogue to the take-home): https://helpcenter.enterpret.com/en/articles/12131693-webhook-integration
  - `POST https://api.enterpret.com/webhook/custom/all`, header `api-key`.
  - Limits: 2000 req/min max (an older/other source says recommended 100 RPM), 200 KB per request, ~100 records per batch.
  - Errors return `msg`, `code`, `referenceID`; success is HTTP 200.
  - The article has a troubleshooting section "If the API returns 200 OK but records don't appear in your dashboard" (verified 2026-10-03), so a 200 is an accept, not a processing guarantee.
  - Codes: `ErrCodeInternalError` 500 (retriable), `ErrCodeInvalidRequestArgument` 400, `ErrCodeMissingRequiredField` 400, `ErrCodeRateLimitExceeded` 429 (retriable), `ErrCodePayloadTooLarge` 413.
  - Setup: Integrations -> +New Integration -> Webhook; choose Feedback, User or Account integration; description of source and feedback type required.
- Users/accounts webhooks: see section 3 (https://helpcenter.enterpret.com/en/articles/8611269-syncing-users-and-accounts).
- Export API v1 (pull out, Bearer token): `POST /export/external/v1/async/submit` returns `queryID`, then `POST /export/external/v1/async/fetch`; filters by source, metadata (EQ/GT/LT/GTE/LTE), language, labels, AND/OR; time range absolute or relative. https://helpcenter.enterpret.com/en/articles/9618433-data-export-api
- Export API 2.0: `POST /external/v2/objects` (list objects), `POST /external/v2/export` (signed CSV URLs), `startTime`/`endTime` ISO 8601, `cursor` pagination, upsert by primary id; objects `feedback_record`, `feedback_summary`, `product_taxonomy_l1..l3`, `theme`, `subtheme`. https://helpcenter.enterpret.com/en/articles/13452140
- MCP server tools: `search_knowledge_graph`, `execute_cypher_query`, `get_schema`, `get_organization_details`. https://www.enterpret.com/blog/model-context-protocol-mcp-server-native-integrations-claude-notion-glean-chatgpt (via search summary)
- Not found: a standalone OpenAPI/Swagger reference. Docs live in the help center.

## 7. Pricing

- No public pricing page (the `/pricing` URLs I tried returned 404). Custom quote based on data volume and number/type of integrations; long transcripts (Gong) cost more than short reviews; no permanent free plan; no seat limit. https://toolradar.com/tools/enterpret/pricing (third party)
- Third-party purchase data: median about $30k/yr, range about $22.6k to $124.7k (5 purchases). https://www.vendr.com/marketplace/enterpret
- Mutable Records costs extra. https://helpcenter.enterpret.com/en/articles/9019938-mutable-records
- No named plan tiers found.

## 8. Vocabulary

| Term | Meaning | Source |
|---|---|---|
| Feedback source / Integration | A connected tool | https://helpcenter.enterpret.com/en/articles/6446339-what-are-feedback-sources |
| Feedback Record | One unit of feedback; `RecordType*` | https://helpcenter.enterpret.com/en/articles/9618433-data-export-api |
| `fileID` | Webhook field naming the source | webhook article |
| Metadata | Typed key/value context on a record | https://helpcenter.enterpret.com/en/articles/6693183-view-manage-metadata |
| Users / Accounts | Customer entities attached via shared id | https://helpcenter.enterpret.com/en/articles/8611269-syncing-users-and-accounts |
| Adaptive Taxonomy | 5-level hierarchy | https://www.enterpret.com/platform/adaptive-taxonomy |
| Keywords L1 / L2 / L3 | "What": product area -> feature -> sub-feature | https://helpcenter.enterpret.com/en/articles/12665751-what-is-the-taxonomy |
| Themes / Sub-themes | "Why": underlying intent | same |
| Categories | Intent classes: Help, Improvement, Complaint, Praise (replace plain sentiment) | same |
| Reasons | Older taxonomy unit ("Categories, Reasons and Keywords"); label type `REASON` in export API | https://www.enterpret.com/blog/enterpret-taxonomy-revolutionizing-the-way-companies-use-customer-feedback |
| Labels / predictions | Per-record tags with `labelID` and confidence; label types REASON / ASPECT / SENTIMENT | Export API v1 page |
| Customer Knowledge Graph | Entity graph over feedback, users, accounts, products | https://www.enterpret.com/changelog/october-2025-product-highlights |
| Wisdom | AI Q&A over feedback, with citations; also a Slack app | https://helpcenter.enterpret.com/en/articles/14403012-enterpret-wisdom-for-slack |
| Feed, Feedback Stream | Saved filtered view and real-time stream | https://helpcenter.enterpret.com/en/articles/9355844-feed-basics |
| Mutable Records / Dynamic Feedback Ingestion | Update a record after first ingest | https://helpcenter.enterpret.com/en/articles/9019938-mutable-records |
| Close the Loop | Detect issue resolution and track impact | https://www.enterpret.com/ |

## Implications for our take-home

Items 1-9 are design suggestions; the mapping to Enterpret's behaviour is documented above, the "good fit" judgement is **[inference]**.

1. Record schema: use a unified envelope `{id, source, type, created_at, metadata, content}` with `type` in `{review, survey, conversation, forum_thread}` (optionally `audio_recording`). Mirror their naming: "feedback record", "source", "metadata". Keep `source_record_id`/`id` separate from your own internal UUID.
2. Content by type: reviews have `text`; conversations have `msgs[] {actor in user|agent|bot, text}`; surveys have `responses[] {question, answer, selected_options}`; forum threads reuse the conversation shape with first message as the original post. This is how Enterpret models it and normalises Discourse/Intercom/Zendesk.
3. Typed metadata: store metadata as a flat dict of string / number / boolean values, reject mixed types per key, and put plan, app version, country, NPS, tier there rather than as top-level columns. Add per-key coverage and unique-value counts as a cheap "metadata catalogue" endpoint if there is time (they show both in the UI).
4. Connectors: pick sources that cover their three ingestion modes: a push webhook (generic `POST /ingest`), a pull poller (Discourse categories or Intercom resolved conversations on a 4h-style interval, with a watermark), and a CSV import. Use their exact source names (Intercom, Discourse, Apple App Store, Google Play, Zendesk, Typeform, CSV Upload, Webhook). Store `source` per record and per-tenant source configuration with a distinct credential each.
5. Idempotency/dedup: dedupe on `(tenant, source, id)`. Make "replace on same id" the default or a flag, mirroring their "mutability disabled by default, replace not merge". Keep `created_at` immutable after first insert (their timestamp rule) and record `ingested_at` separately. Document that near-duplicate text dedup is out of scope, as it is undocumented on their side.
6. Validation/limits that match theirs: epoch-seconds `created_at`, reject future and pre-2000 values, accept 13-digit ms and convert, batch cap ~100, payload cap 200 KB, structured errors `{msg, code, referenceID}` with retriable vs non-retriable codes (400 vs 413 non-retriable; 429 and 500 retriable), 429 on rate limit.
7. Multi-tenancy: tenant = "workspace" (carry `org_id` on every record, per-integration API key in an `api-key` header, never trust a tenant id in the body). Roles Admin / Editor / Member / Viewer are optional; at minimum, only admins can create or edit integrations.
8. PII and language: scrub on ingest, before persistence, using placeholders `[EMAIL]`, `[NAME]`, `[PHONE]`; keep a pluggable per-tenant custom pattern list. Store `language` (ISO code) and leave a `text_en` slot with a stub translator, since their export carries `textEn`/`conversationEn`.
9. Downstream placeholders (do not build the ML): include `predictions`/`labels: []` with `{label_id, type: reason|aspect|sentiment, confidence}`, `summary`, and `languages` on the stored record, plus a taxonomy stub with Keywords L1/L2/L3, Themes, Sub-themes and the four Categories (Help, Improvement, Complaint, Praise). Mention "Reasons" as the older name in the README so reviewers see you know both.
10. Users/accounts: if scope allows, a second, tiny `users`/`accounts` ingest (id, createdAt, attributes, max 15 per call) with linking via a metadata field such as `user_email`. This is the hook for "customer attributes (plan, ARR)" and is a distinctive Enterpret feature.
11. Incremental pull design: copy their patterns, a high-watermark column (their `ERC_ROW_CREATED_AT`) for warehouse-style sources, a fixed poll interval (4h in prod; make it configurable and short in tests), resolved-only filter for support tools, and initial backfill separate from incremental sync. Note the Intercom caveat as a known trade-off: re-fetching a whole conversation can create duplicates unless you key on the conversation id.
12. Export endpoint: offer `GET /feedback` with filters by source, type, time range, language and metadata (EQ/GT/LT) and cursor pagination, since their Export API exposes exactly those filters.
13. README framing: state which of their behaviours you copied (envelope, typed metadata, replace-on-same-id, error codes) and which you deliberately skipped (ML taxonomy, knowledge graph, Wisdom, MCP). Pricing/plan tiers are not public, so nothing to model there.
