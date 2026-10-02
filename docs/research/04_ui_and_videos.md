# 04 - Enterpret product UI: what users actually look at

Researched 2026-10-03 with the built-in browser (no sign-in, no downloads, no images saved).
Legend: **[SEEN]** = read on a page or visible in a video frame; **[DOC]** = stated in the public Help Center text;
**[INFER]** = my inference, not directly shown. Video frames were ~530px wide, so small UI text was only partly
legible; where a label was blurry I say so.

Public Enterpret has no self-serve demo or recorded click-through of the Feed itself. The closest things are the
marketing/product videos below and the Help Center (which describes the Feed, metadata and taxonomy UI in words and
gives the exact webhook schema). Long customer talks (Notion 43 min, Canva 3:43 story, ElevenLabs 46 min) were NOT
inspected.

---------------------------------------------------------------------------------------------------

## A. Videos

### A1. "Introducing Enterpret 2.0: A new era for Customer Intelligence" (3:36)
URL: https://www.youtube.com/watch?v=brTWaZCvTq4  (289k views; channel https://www.youtube.com/@Enterpret/videos, 76 videos)

Shows: founder talking head cut with product motion graphics: Unify -> Understand -> Act, feedback list, Adaptive
Taxonomy, Wisdom AI, AI Agents.

Key frames:
- ~0:40-1:00: talking head, caption "Your customers are telling you...". Slide at ~1:00: three boxes
  **Unify** ("All your feedback, woven with business context - automatically"), **Understand** ("From metrics to
  meaning - instant, explainable insights"), **Act** ("Insights that get assigned and acted upon").
- ~1:20 (feedback record list, the most useful frame). Top-left toggle tabs **Summary | Feedback**; top-right
  **Quantify** and **Ask Wisdom**. Below, a vertical list of cards. Each card, top line = small source icon + date
  ("Aug 26 2025" style) + a user/e-mail handle + platform/device (e.g. Web, Android, iOS, MacOS) + a company/account
  name, all dot-separated in small grey type. Then 1-3 lines of verbatim customer text. Then small grey/colored
  **tag chips** under the text (seen: "Collaborative Whiteboard", "Virtual Meetings", "User Interface",
  "Integrations", "Security", "Meetings", "Meeting Controls"). Caption at that moment: "When users complain about
  audio quality,...". Exact handle strings were blurry [INFER: top line = `date . user . platform . account`].
- ~2:00: **Adaptive Taxonomy** screen. Title "Taxonomy . Last edited 2 weeks ago", a help "?" and kebab menu.
  Search box "Search feedback by keyword, themes or metadata...". Three columns: **Level 1 Keywords (19)**,
  **Level 2 Keywords (4)**, **Level 3 Keywords (5)**, each row with a count. L1 rows seen: Meetings 24,410;
  Team Chat 16,816; Workflow Automation 3,373; Webinars 122; Phone 83; Whiteboard 83; Events 75; Contact Center 59;
  Rooms 37. L2 rows (under selected L1): Cross-Product Integration 74, Third Party Connections 10, Payment Methods 1,
  Call Transcripts 154 (selected). L3 rows: Calendar Integration Workflows 171, Permissions 143 (selected),
  Meeting to Docs Workflows 1, Miscellaneous 0, Meeting to Chat Escalations 0. A sample verbatim sits above the panel
  with two chips: a green "Call Transcripts" (keyword) and a red "Permissions" (theme-ish). Caption: "This taxonomy
  evolves as you grow." (Counts look like a demo/Zoom-like tenant; treat as illustrative.)
- ~1:50 (just before the taxonomy screen): slide "Adaptive Taxonomy" heading with a blank card titled "Calendar Integration Workflows - View 16 Records"
  [SEEN, partly legible] -> drill-down from a taxonomy node to its records.
- ~2:50: **AI Agents** panel with four cards: Quality Monitor Agent, Escalation (Shield) Agent, Newsfeed Agent,
  Close the Loop Agent. ~3:10: Close-the-Loop card, with a drafted ticket body and **Jira** and **Linear** logos;
  caption: "...automatically notifies affected customers when resolved."

### A2. "Wisdom - The AI Copilot for Customer Insights" (1:21)
URL: https://www.youtube.com/watch?v=OXgvNJLzN-A  (231k views)

Shows: chat UI inside a tablet frame (purple/magenta backdrop).
- 0:08: Wisdom logo (purple "W"), prompt "What are the top complaints about Spotify playlists?", a small
  dropdown button reading **"View stages"** [SEEN, partly legible], input "Ask Wisdom" with send arrow.
- 0:28: answer view. Top: a small trend line chart (x-axis months). Question "Why are customers facing issues with
  auto-adding songs to playlists?". Answer is a bullet list of bold issue titles
  ("Unwanted Auto-Adding of Songs to Playlists", "Difficulty in Removing Auto-Added Songs", "Disruption of Listening
  Experience", "Limitations of Shuffle Feature"). Inline purple **theme chips** are embedded in sentences, in the form
  "# Issue With Auto-Adding Songs To Playlist" with small superscript citation numbers (footnote style).
  Naming pattern of the theme: `Issue With <thing>` / `Difficulty In <thing>` [SEEN].
- 0:48: follow-up typed: "...Please give me a list of customers who..." (blurry) - i.e. from a theme to
  the customers who reported it.
- 1:06: end card "Unified Customer Feedback Intelligence - fast, easy to use, and powerful".

### A3. "New in Adaptive Taxonomy: Make edits with confidence" (1:15)
URL: https://www.youtube.com/watch?v=PyuKL413Qak

- 0:10: split screen. Left = a table titled **Themes** (column header "Feedback Records" on the right), many rows
  prefixed by a status icon (green check = healthy, amber triangle = needs attention) and a chevron to expand into
  sub-themes. Left of the table a y-axis of counts (1,000s) [SEEN]. Right = a chat panel with the **Enterpret** agent
  ("Let's walk through it one at a time").
- 0:30: slide "Three new capabilities, one workflow": **Chat with your taxonomy**, **Double-check** ("Get suggestions
  before changes go live"), **Safety rails** ("Rename, merge, split, move - with guardrails").
- 0:50: pending-change review in the chat: "Ready to commit?" with button **Save Changes** and **Discard**; proposed
  edits listed with follower/record counts.
- 1:06: title card "Your Adaptive Taxonomy just got smarter".

### A4. "New in Escalation Shield: Automation triggers..." (0:29)
URL: https://www.youtube.com/watch?v=nPUIGz2n2Yk  (only one usable frame; the second frame did not render)

- 0:06: dark UI with three floating signal cards on one account: a **Zendesk** ticket ("Scheduled export came through
  empty again."), an **Amplitude** event ("export_completed: 6 runs, 0 rows returned"), an **Intercom** chat ("Can
  someone actually look at this? Third time this week?"). Each card has a small source logo + source label + type
  (ticket / chat / event) + relative time ("... min ago") + account label. Caption text: "One account, three signals
  in ten minutes: a ticket, a failing export, a chat." Section label "ESCALATION SHIELD - now acts on what it finds".
  Takeaway: alerts are cross-source, per-account, time-windowed [SEEN]; card chrome details [INFER].

### A5. "Introducing Agent OS: customer intelligence that starts itself" (1:39)
URL: https://www.youtube.com/watch?v=A0fbgPHMxQg  (one usable frame; ads covered the other)
- 1:15: a Slack workspace "Acme Corp", channel `#payments-launch`, message from a bot-like agent: "Heads up. Refund
  requests are spiking on Checkout v2.3.1x baseline across 4 accounts. I've filed RW-1008 and looped in the team."
  -> alerts land in Slack with a Jira/Linear-style ticket key [SEEN].

---------------------------------------------------------------------------------------------------

## B. Web pages

### B1. https://www.enterpret.com/ (homepage)
Positioning: "Customer intelligence infrastructure". Pillars: Adaptive Taxonomy, Customer Context (who/what product
area/how important), Feedback loop. Verticals: Customer, Support, Sales, Market Intelligence. 50+ sources, MCP server,
native Slack/Jira/Linear. Hero video = Canva customer story (Hc2IPgGOEas). Nav: Platform, Solutions, Customers,
Resources, LOG IN (dashboard.enterpret.com), TRY ENTERPRET, BOOK A DEMO. No embedded UI screenshots in the text layer.

### B2. https://www.enterpret.com/platform/customer-feedback-integration  (ingestion / sources)
- "50+ native connectors", "one-click activation (OAuth, <60 s)", "auto-classification on ingestion".
- Custom ingestion: **Webhook API**, **Data warehouse sync** (Snowflake, Census), **File upload** (CSV).
- Governance: admin-only connectors, **Ingestion blockers & PII** (SSN / credit card obfuscation before ingestion),
  **24/7 health monitoring** - "automated health checks every 3 hours", alerts on connection issues or data staleness.
- Upload product docs/help articles/changelogs as business context.

### B3. https://www.enterpret.com/platform/data-enrichment  (fields and metadata)
- Unify cross-source fields: "Map 'User ID', 'Reporter', 'Author' into a single identifier".
- Custom AI prompts and Python functions create new fields (NPS, SLA / resolution times); ingest + batch/backfill.
- Normalise ids, country codes, dates. Enriched fields are usable in filtering, sorting, quantifying.

### B4. https://www.enterpret.com/platform/dashboards-and-reporting
- Terms: **Feed**, **Quantify** ("Quantify impact": rank themes by ARR, CSAT, NPS, not volume), dashboards, scheduled
  reports (Slack/email), "Feed views & summaries" (toggle verbatim vs AI Summary), anomaly detection + proactive
  alerts to Slack/email, "Saved items & templates", VoC templates for Product / CX / Leadership.
- Dashboard filters use "entities and metadata from your Knowledge Graph".

### B5. https://www.enterpret.com/platform/adaptive-taxonomy
- 5-level hierarchy: **L1 / L2 / L3 Keywords** (product area -> feature -> sub-feature) + **Themes / Sub-themes**.
- "Explainable insights: inspect the rationale behind every classification", "Intelligent editing", "Proactive
  maintenance (drift, duplicates, emerging terms)", "Assign ownership: map L1/L2/L3 to teams and auto-route".

---------------------------------------------------------------------------------------------------

## C. Help Center (text descriptions of the real UI) - https://helpcenter.enterpret.com/en/

Collections seen: Feed, Quantify, Dashboards, Taxonomy, Collection, Synced Users and Accounts, Custom Filters,
Integrations (64 articles), Improving your Predictions, Sales Insights, Agent OS, Enterpret MCP.

### C1. Feed: Basics - /articles/9355844-feed-basics [DOC]
- Feed = "a saved view of feedback records that match filters" (live search). Time-period selector top right
  ("Last X Days/Weeks/Months"). **Enterpret query builder**; filter by content, metadata, keywords, or Reasons;
  button **Apply Filters**.
- Two views: **Feedback** (verbatim) and **Summary** (AI-generated). Buttons **SAVE**, **SUBSCRIBE** (email or Slack
  channel + frequency), "View Feed" button in digests, "Subscribed" state with edit icon.

### C2. View & Manage Metadata - /articles/6693183-view-manage-metadata [DOC]
- Metadata = "everything captured alongside a feedback record that is not the feedback text". Examples by source:
  App/Play Store: score, app version; SurveyMonkey: survey title, score; Intercom: user plan type, custom tags;
  Slack/Discord: channel.
- On every record: **starred** fields are shown first (max **2 starred per source**); a **Show Metadata** button
  (arrow, bottom right of the card) reveals all. A **Go to source** icon on the card links back to the source;
  for FileUpload / Webhook / Snowflake the admin picks one metadata field to act as the **source link**.
- Query builder example: `App Store > Rating is in [4]` then **GO**.
- **Manage Metadata** page (Integrations > Manage Metadata card, admin only) columns: **Starred, Name,
  Original Name, Data Type (string/number/boolean), Unique Values, Coverage (% of records with value), Visibility**
  (hidden = cannot be grouped/filtered).

### C3. Unified Fields - /articles/8830079-unified-fields [DOC]
- Merge per-source fields into one: e.g. "Playstore Score" + "Appstore Rating" -> **App Rating**;
  Intercom "Conversation ID" + Zendesk "Ticket ID" -> **Ticket ID**. Admin only. Usable in search bar filters,
  Quantify "Show me" + filters, and Manage Metadata. Materialised at ingestion for speed.

### C4. Taxonomy - /articles/12665751-what-is-the-taxonomy and /8102808-what-are-categories [DOC]
- **Keywords** L1/L2/L3 = "what the feedback is about" (fields: Name, Description, Level). Special: "Not Specified",
  "Misc".
- **Themes / Sub-themes** = "why the feedback was given" (replaced the older "Reasons" concept). Fields: Name,
  Category. Special: "General", "Misc". Theme->Sub-theme 1:N; Theme<->Keyword M:N.
- **Categories** (exactly 4): **Complaint, Help, Improvement, Praise**. Theme name examples: "Issue: Trouble
  Downloading Zoom", "Help with Using New Update", "Improvement: Ability to Customize Virtual Backgrounds",
  "Praise: Happy with Picture Quality".
- Worked example: one verbatim -> Keywords "Account" and "Payment > Billing > Refunds"; Theme "Issues with unexpected
  charges" / Sub-theme "Refund request to unexpected charge post account deactivation" / Category Complaint; a
  second theme "Issues with Support availability" -> record has multiple taxonomy paths.

### C5. Editing Predictions - /articles/7188208-editing-predictions [DOC]
- Each record has **predictions** = full path (L1 -> L2 -> L3 keyword + theme + sub-theme); a record can carry several.
  Inline "Edit Predictions" (Keywords-first / Themes-first), trash icon to delete a path. Roles: Admin / Editor can
  edit, Members read-only. Available in search results, Quantify drill-downs, dashboard record views, Wisdom citation
  drawers.

### C6. Webhook Integration (the ingest contract) - /articles/12131693-webhook-integration [DOC, exact]
- Setup: Integrations > **+New Integration** > "Webhook" > type **Feedback / User / Account Integration**;
  **Display Name** (becomes the source name shown on records) + **description** (improves summary/prediction quality);
  API key shown on the integration page.
- `POST https://api.enterpret.com/webhook/custom/all`, header `api-key: ...`. Limits: 2000 RPM, 200 KB/request,
  <=100 records/batch.
- Envelope `{"records":[{id, fileID, type, createdAt, metadata:{metadata:{...}}, ...}]}`.
  `type` in **REVIEW, CONVERSATION, SURVEY, AUDIO_RECORDING, FORUM_CONVERSATION_THREAD**.
  `createdAt` = Unix **seconds** (ms auto-converted; <2000-01-01 or future rejected). `metadata` is required (may be `{}`).
- REVIEW: `text` required. CONVERSATION: `conversation.msgs[] {actor in user|agent|bot, text}`.
  SURVEY: `surveyResponse.responses[] {question, answer | selectedOptions}`.
  AUDIO: `audioRecording.audioURL` (+ optional transcript units with actor, actorID, text, startTime/endTime).
- Metadata typing: `{"field": {"array": {"s"|"n"|"b": [values]}}}`; one type per field (mixing -> ErrCodeInvalidFieldFormat).
  Example metadata keys: rating, platform, nps_score, user_segment, user_tier, lifetime_value, channel, language.
- **Dedupe/mutability**: duplicate `id` skipped by default; with "data mutability" on, the record is replaced
  (metadata and conversation.msgs replaced, not merged/appended). id -> deterministic UUID, case-sensitive.
- Errors: `{msg, code, referenceID}`; codes ErrCodeInternalError (500, retriable), ErrCodeInvalidRequestArgument (400),
  ErrCodeMissingRequiredField (400), ErrCodeInvalidFieldFormat (400), ErrCodeExceededBatchLimit (400),
  ErrCodePayloadTooLarge (413), ErrCodeRateLimitExceeded (429, retriable), ErrCodeInvalidAPIKey (401).
- Gotcha documented: a 200 OK can still drop records (empty message text sanitised away; legacy webhooks).

### C7. Feedback Record Timestamp Handling - /articles/14088289-feedback-record-timestamp-handling [DOC]
- Field name **record_timestamp** (= feedback creation time) is **immutable after first ingest**; resend with same id
  and new timestamp is ignored; to fix: delete records then re-send. Applies to Snowflake (`ERC_CREATED_AT`, `ERC_ID`),
  Webhook, File Upload. Recommend UTC.

### C8. Integration Activation Guide + "data missing / counts differ" - /articles/6320422, /15526590 [DOC]
- Inbound **pull-based** (native, OAuth) vs **push-based** (webhook, SFTP, file upload, Snowflake). Outbound: Slack
  reports/alerts, email, Jira, Linear, webhooks, Export API. Admin-only management.
- Per-integration page: source name, type, selected object/channel/survey/table, sync conditions/filters, field
  mapping as **feedback fields** (customer language) vs **metadata fields** (context). "Connected" does not mean fully
  synced; counts differ from source because of scope, date range, field selection, and record shape (one ticket =
  many messages), historical backfill limits. Users/Accounts sync uses unique ids + created-at + linking fields.
  Integration description improves prediction quality. Pre-ingestion filters to control volume.

### C9. Export API 2.0 - /articles/13452140-export-api-2-0 [DOC]
- Base `https://api.enterpret.com/export`, `Authorization: Bearer <token>`; `POST /external/v2/objects`
  (list exportable objects) and `POST /external/v2/export` {objectID, startTime, endTime?, cursor?} -> signed URLs to
  CSV files; window is by **created/updated inside Enterpret**, not source time.
- Object ids: **feedback_record, feedback_summary** (one record can have several summaries, e.g. per audio chapter),
  **product_feedback_envelope** (the predictions / taxonomy assignments), **product_taxonomy_hierarchy**
  (rows of l1,l2,l3,theme,subtheme ids), **product_taxonomy_l1/l2/l3, theme, subtheme**.

---------------------------------------------------------------------------------------------------

## D. Record anatomy as shown in the UI

Single feedback card in the Feed (Feedback view) [SEEN video A1 + DOC C2, C4]:

| Zone | What is displayed | Notes |
|---|---|---|
| Header line | source icon/logo + **source name** (= integration Display Name), **date** (record_timestamp), user handle/email, account/company, platform/device | dot-separated, small grey; which metadata appears here = the **starred** fields (max 2 per source) [DOC], rest [INFER] |
| Body | verbatim customer **text** (or, in Summary view, an AI-generated **summary**) | Feedback vs Summary toggle at top of the Feed |
| Chips | taxonomy tags under the text: **Keywords** (L1 > L2 > L3, e.g. "Playback > Offline Listening"), **Theme / Sub-theme** (e.g. "Issue With Auto-Adding Songs To Playlist"), coloured by **Category** (Complaint / Help / Improvement / Praise) [SEEN colour variation; mapping colour->category INFER] | a record can have several paths ("predictions") |
| Footer | **Show Metadata** expander (all remaining fields), **Go to source** link, **Edit Predictions** pencil (Admin/Editor) | |
| Sentiment | NOT shown as a separate labelled field in anything I saw. Closest = Category (Complaint/Praise) and ratings/NPS/CSAT in metadata; the homepage says "Shifts in customer sentiment" and enrichment can compute sentiment as a custom field [INFER: sentiment = derived/enriched or category-based] | |
| Impact | not on the card; **Quantify** ranks themes by volume / ARR / CSAT / NPS using account/user data joined via synced Users & Accounts | |

Underlying record fields (from ingest contract, C6/C7): `id`, `fileID` (source/stream id), `type`
(REVIEW | CONVERSATION | SURVEY | AUDIO_RECORDING | FORUM_CONVERSATION_THREAD), `createdAt` (unix s) -> shown as
`record_timestamp`, content (`text` | `conversation.msgs[{actor,text}]` | `surveyResponse.responses[]` | `audioRecording`),
typed multi-valued `metadata`. Derived server-side: `feedback_summary` (1..n), `predictions` / `product_feedback_envelope`
(1..n taxonomy paths: l1,l2,l3,theme,subtheme,category).

Filters/Query builder vocabulary: time period ("Last X days/weeks/months"); content (text search); metadata
(`<Source> > <Field> is in [...]`, e.g. App Store > Rating); unified fields; Keywords (L1/L2/L3); Reasons/Themes;
saved **Custom Filters**; cohorts; Feed save/subscribe. Source filter value e.g. `source=webhook`, `source=fileupload`.

Sources screen (Integrations page): left sidebar item **Integrations**; **+New Integration** search; per-integration
card with status, API key (webhook), description; **Manage Metadata** and **Manage Unified Fields** cards; admin-only.
Health: automated checks every 3 hours; alerts on connection issues/data staleness. Source icons = brand logos
(Zendesk, Intercom, Salesforce, Slack, Gong, App Store, Play Store, Reddit, Snowflake, Amplitude, Jira, Linear...).

Alerts: anomaly detection on themes -> Slack/email "proactive alerts"; **Escalation Shield** (cross-source per-account
signals in a short window); Feed digests (Subscribe); agent posts to Slack with a ticket key.

---------------------------------------------------------------------------------------------------

## E. Implications for our take-home

Record model (adopt these names so it looks familiar):
1. Record envelope: `id`, `source` (integration display name) + `source_type`/`fileID`-like stream id, `type`
   enum {REVIEW, CONVERSATION, SURVEY, AUDIO_RECORDING, FORUM_CONVERSATION_THREAD}, `created_at` exposed as
   **`record_timestamp`** (unix seconds in, ISO out), `text` plus `messages[{actor: user|agent|bot, text}]` for
   conversations. Support only REVIEW/CONVERSATION/SURVEY in the take-home; note the others as out of scope.
2. `metadata`: flat map `name -> typed array` with one type per field (string/number/boolean); keep the
   Enterpret `{"array":{"s":[...]}}` shape only if you want API parity, otherwise accept plain JSON and infer the type
   per field; reject mixed types (their `ErrCodeInvalidFieldFormat`). Always required, `{}` allowed.
3. Server-derived, kept separate from the record: `summaries[]` and `predictions[]` where a prediction =
   `{l1, l2, l3, theme, sub_theme, category}`; `category` is exactly one of **Complaint | Help | Improvement | Praise**.
   Use **Keywords (L1/L2/L3)** for "what" and **Themes/Sub-themes** for "why" (not "Reasons", which they retired).
   Multiple predictions per record. Expose `sentiment` only as an enriched/derived field and label it [our addition].
4. Idempotency/dedupe: deterministic internal id from the caller's `id` (case-sensitive); duplicates skipped by
   default; optional "mutable" mode replaces the whole record (metadata and messages replaced, never merged);
   `record_timestamp` immutable after first ingest. This is cheap to implement and is exactly their documented behaviour.
5. Ingest API shape: `POST /webhook/...` with `{"records":[...]}`, `api-key` header, max 100 records/batch,
   200 KB/request, 429 retriable; errors `{msg, code, referenceID}` with codes named like theirs
   (MissingRequiredField, InvalidFieldFormat, ExceededBatchLimit, PayloadTooLarge, RateLimitExceeded, InvalidAPIKey).
   Validate `createdAt` (seconds, >=2000-01-01, not in the future; auto-convert 13-digit ms). Return per-record
   accepted/skipped counts so there is no silent drop (their documented pitfall: 200 OK but record dropped).
6. Sources: a source/integration registry with `display_name`, `description` (feeds classification), `type`
   (feedback|user|account), `mode` (pull|push), `status`, `last_sync_at`, health check cadence, admin-only mutation,
   PII blockers applied pre-ingest. Demo list should use well-known brand sources (Zendesk, Intercom, App Store,
   Play Store, Slack, Gong, Typeform, Reddit, Webhook, File Upload) with logo/emoji icons.
7. Manage-Metadata equivalent: an endpoint/table returning per-field `name, original_name, data_type,
   unique_values, coverage_pct, starred, visible` and a way to star (max 2 per source) and hide fields; unified fields
   (`App Rating` = Play Store score + App Store rating) as a small mapping table. High value for little code.

Demo / UI (what to show):
- Feed screen: time-period selector, query builder with chips (Source, Metadata field, Keyword L1/L2/L3, Theme,
  Category), **Feedback | Summary** toggle, cards with header line `source icon . date . user . account . platform`,
  verbatim text, taxonomy chips coloured by Category, **Show Metadata** expander (starred fields first), **Go to
  source**. Buttons **Apply Filters**, **Save**, **Subscribe**.
- Taxonomy browser: three columns "Level 1/2/3 Keywords (n)" with counts + a Themes table with record counts and a
  status icon; clicking a node opens its records ("View N Records").
- Quantify/trend: themes ranked by count (and by a numeric metadata field such as rating/ARR), plus a simple anomaly
  flag; an "alert" row in Slack-ish format (`Heads up. <theme> spiking across N accounts`).
- Sources page: connector cards with status/last sync/health + "+New Integration (Webhook)".

Naming to adopt: Feed, Feedback record, record_timestamp, Source, Integration, Display Name, Metadata (starred /
coverage / visibility), Unified Field, Keyword (L1/L2/L3), Theme, Sub-theme, Category (Complaint/Help/Improvement/
Praise), Prediction, Summary, Quantify, Wisdom (skip unless doing NL query), Subscribe, Custom Filter, Collection.

Limits of this research: no authenticated product access; sentiment label, exact card header ordering and chip
colours are inferred from low-res frames. The Notion/Canva/ElevenLabs long-form talks likely contain real screen
shares of the Feed and are the best next source if more fidelity is needed.
