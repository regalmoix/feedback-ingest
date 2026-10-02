# Enterpret: engineering and stack research

Researched 2026-10-03 from public pages only. Tags: **[FACT]** = stated on a cited page. **[INFER]** = my inference. **[GAP]** = searched, nothing public found.
Caveat: pages were read through a summarizing fetcher, so treat exact figures as "verify before quoting verbatim".

## 1. Engineering blog (engineering.enterpret.com)

Only two posts exist as of the fetch, both by Anshal Dwivedi.

### 1a. "The Unorthodox Path: How We Built Enterpret" (12 Nov 2025)
URL: https://engineering.enterpret.com/the-unorthodox-path-how-we-built-enterpret-5/
- [FACT] Go is the primary backend language. Gin for HTTP. Protobuf contracts with a custom RPC abstraction (protobuf-over-HTTP, JSON, gRPC-compatible).
- [FACT] AWS-only, "serverless first": Lambda as primary compute for 8+ years, then ECS for steady-traffic services, AWS Batch (spot) for long jobs, Step Functions for workflows, API Gateway, S3 payload offload, SAM/CloudFormation, GitHub Actions CI/CD.
- [FACT] Go **monorepo**, 26 microservices (started at 8 services / 35 Lambdas, 2 engineers + 1 intern). Shared libs for errors, RPC, utils. Generated clients.
- [FACT] Lambda fit "bursty ingestion": pay per execution, zero idle cost, near-instant elasticity.
- [FACT] Pain points: cold starts hurt dashboards (moved to ECS); 15-minute limit (moved to Batch); 6 MB payload limit (S3 offload); API Gateway 29 s timeout; unbounded Lambda concurrency starved critical services, so they set explicit concurrency limits in IaC.
- [FACT] Logic is separated from the deploy entrypoint, so a service moved Lambda to ECS "in less than a day".
- [FACT] Observability (metrics, logs, tracing) is built into the shared RPC layer, with standardized error codes and log formats. CloudWatch cost once exceeded compute cost. Weekly bill reviews.
- [FACT] **Blackhole** is the ingestion system: "minimal upfront abstraction", supports 50+ integrations (Slack, Zendesk, social, surveys) over 5 years without core rewrites.
- [FACT] Quotable principles: "Small designs compound over time", "Design systems that evolve, not expand", favor managed services, commit to one cloud, design for horizontal scale from day one.

### 1b. "KOSH: The Knowledge Graphs That Power Enterpret" (1 Feb 2026)
URL: https://engineering.enterpret.com/kosh-the-knowledge-graphs-that-power-enterpret/
- [FACT] Three layers: Core Graph (objects, schemas, records, relationships); System Intelligence (**Blackhole** ingestion, **Inference Platform** enrichment); User Intelligence (taxonomy, transformations).
- [FACT] Primitives: Objects (static + dynamic schema), Records (version metadata, timestamps, merge history), Relationships as first-class edges.
- [FACT] Flow: ingest and normalize, write to core graph, enrich (classify, extract, link), **CDC** to downstream projections.
- [FACT] Projections: ClickHouse for analytics (self-managed, shared cluster), plus search/retrieval and semantic projections.
- [FACT] **Schema-on-write**: new attributes seen at ingest trigger runtime DDL in ClickHouse. Type is encoded in the column name (`field__s`, `field__n`, `field__b`).
- [FACT] **Self-healing sync**: DDL events are ordered per tenant/object, and missing ones are repaired by diffing primary against analytical store.
- [FACT] **Eventual consistency by design**. Version-based conflict resolution: stale/out-of-order updates are rejected and do not overwrite newer versions.
- [FACT] Deliberate ~15-minute freshness window on the analytical side to batch writes to very wide tables.
- [FACT] Event partitioning by tenant and object type so one customer's schema explosion cannot block others. Incidents named: sync failures, queue clogging from malformed DDL or oversized batches, noisy neighbors on the shared cluster.
- [FACT] Scale: "hundreds of millions of records and updates per day"; Account objects commonly have 500-700+ dynamic attributes, one customer 800+ (Salesforce).

## 2. Job postings and stack (Greenhouse: https://job-boards.greenhouse.io/enterpret)

Open engineering roles (all Bengaluru, onsite): Applied AI Research Engineer (7580532003), MTS Core Product (7891458003), MTS Platform (7915008003), Principal Engineer Core Product (7821474003), Staff SWE Platform (7915246003), plus a Senior PM, Integration Ecosystem (7857960003). Backend SWE Intern also seen (7847134003).
- [FACT] Stack words used: **Golang**, Python, serverless, SQL/NoSQL, ElasticSearch, GraphQL, **DynamoDB, ClickHouse, Snowflake**, AWS, knowledge graphs, model hosting/inference, "data pipelines, event-driven architectures". Staff Platform: https://wellfound.com/jobs/4612748-staff-software-engineer-platform
- [FACT] Staff Platform asks: "design systems for projected 1-2 year growth", decisions "hard to reverse", track latency/availability, "reduce cost per feedback record", root-cause production issues.
- [FACT] MTS Platform: "reliability, latency, performance, operational readiness", baselines, metrics, runbooks, "high-throughput data systems or async pipelines", "AI-native working style", first-principles thinking, open-source use.
- [FACT] MTS Core Product: "backend infrastructure powering data ingestion through real-time analytics", "deep system observability for early failure detection", trade-offs among performance, cost, longevity.
- [FACT] Principal Core Product (Wisdom and Agents platform): trade-offs across "correctness, latency, UX, AI/model behavior, reliability, cost, delivery speed"; "AI-native from the ground up".
- [FACT] Integration PM posting is the best source on ingestion-quality language: own "completeness, latency, and error rates", per-integration **error taxonomies**, webhooks / rate limits / deprecation cycles, agent-driven setup that "inspects customer sources and proposes configurations".
- [FACT] Kafka/Postgres/Redis are not named anywhere. Do not claim they use them. [INFER] Queues are likely SQS/SNS/EventBridge/DynamoDB Streams given AWS-serverless; unconfirmed.

## 3. GitHub / open source
- [FACT] https://github.com/Enterpret returned 404. [GAP] No public org or repos found. Job posts say they "use open source and contribute back" but no repos are visible.

## 4. Interview process and values
- [GAP] No public mention of a "System Design AI Native" round or the take-home format. Glassdoor returned 403.
- [FACT, weak, third-party aggregators] Process is roughly: screen, DSA round, **machine coding round** ("translate requirements into working, maintainable code, explaining design decisions"), then a discussion/HR round. https://www.glassdoor.com/Interview/Enterpret-Interview-Questions-E6020935.htm (search snippet only).
- [FACT] Values (https://www.enterpret.com/careers): "Be an Owner, Not a Renter"; "Care Personally, Challenge Directly"; "Humble Growth Mindset"; principles "Seek Truth" (opinions are starting points, not facts), "Narrow the Focus, Up the Intensity".
- [INFER] Machine-coding emphasis plus the engineering blog suggests they reward small, clear designs with explicit trade-offs and AI-assisted but verified output.

## 5. Founders' and product's public technical claims
- Founders: Varun Sharma (CEO; ex-Amplitude, employee 15) and Arnav Sharma (CTO; ex-Uber SWE). Press list: https://www.enterpret.com/company/press . Podcast page fetched (https://unchartedpodcast.co/episodes/varun) had no transcript. [GAP] No public deep-dive on ingestion, dedup, or incidents from founders.
- [FACT] https://www.enterpret.com/blog/why-customer-intelligence-requires-infrastructure-not-just-ai : "battle-tested extractors for 50+ sources" handling actor attribution, thread hierarchy, speaker diarization, Q&A pairing, metadata normalization; entity resolution linking feedback to customers/accounts/revenue; "classification happens once, when feedback arrives, against stable definitions".
- [FACT] https://www.enterpret.com/blog/how-to-analyze-millions-of-pieces-of-customer-feedback-reading-them-is-the-easy-part : taxonomy **construction is one-time/expensive, tagging is repeated millions of times**; candidate-label filter built on "dropping a correct candidate is ten times worse than keeping a wrong one"; all five levels predicted as one path so counts reconcile; "keep the tree flat and wide"; recall 48.7% to 92.3% when nodes carry descriptions.
- [FACT] https://www.enterpret.com/guides/the-5-reasons-ai-feedback-analysis-gets-less-reliable-as-volume-grows : LLM counts vary 8-10% between identical runs; chunking fragments themes into near-duplicates; a persistent taxonomy cut churn 86%.
- [FACT] Taxonomy changelog: https://www.enterpret.com/changelog/taxonomy-model-updates-merge-suggestions-and-less-duplication : merge suggestions, 92% fewer obvious duplicates at ~93% merge precision.
- [FACT] Platform page https://www.enterpret.com/platform/feedback-integration : OAuth in under 60 s; PII (SSN, card numbers) detected and obfuscated **before ingestion**; field unification; auto-classification on arrival; integration health checks **every 3 hours** with staleness alerts; ingestion paths = native connectors, webhook API, warehouse sync, CSV backfill.
- [FACT] Vendor checklist https://www.enterpret.com/guides/data-ingestion-checklist-7-questions-to-ask-every-feedback-vendor : "ingestion cadence sets the ceiling on how early you can catch anything"; backfill must apply the same taxonomy; no public numbers on dedup, idempotency, latency SLAs.
- [FACT] Customer scale: Canva "200M+ feedback analyzed" (https://www.enterpret.com/).

## 5b. Public ingestion API (the closest thing to their real contract)
Source: https://helpcenter.enterpret.com/en/articles/12131693-webhook-integration (re-fetched once to confirm limits; one earlier search snippet said 20 RPM/1 MB, which looks stale).
- [FACT] `POST https://api.enterpret.com/webhook/custom/all`, header `api-key`, JSON.
- [FACT] Body `{"records":[...]}`. Required per record: `id` (unique string), `fileID` (source id), `type` (REVIEW | CONVERSATION | SURVEY | AUDIO_RECORDING | FORUM_CONVERSATION_THREAD), `createdAt` (Unix **seconds**, >= 2000-01-01, not in the future), `metadata` (required even if `{}`).
- [FACT] Limits: 2000 RPM, 200 KB per request, recommended <100 records per batch (the error table says batch limit 100).
- [FACT] Typed metadata arrays keyed `s` / `n` / `b`; one type per field, mixing returns `ErrCodeInvalidFieldFormat`.
- [FACT] **Dedup/idempotency**: duplicate `id` is skipped by default. "Mutability" (full replace on same `id`, no merge, do not use to append conversation messages) is off by default and enabled by support.
- [FACT] Errors: `{msg, code, referenceID}`; 400 non-retriable (`ErrCodeMissingRequiredField`, `ErrCodeInvalidFieldFormat`, `ErrCodeExceededBatchLimit`), 401, 413, 429 and 500 retriable. 200 means accepted, not processed.
- [FACT] Legacy webhooks (before Aug 2025) used a lenient sanitiser that could silently drop malformed records; new ones validate strictly. Good evidence they care about silent loss.
- [FACT] Privacy delete API: `POST /webhook/delete/custom`, max 100 IDs, processed in batches "within 24 hours (configurable)", cascades account to users to records. https://helpcenter.enterpret.com/en/articles/9167288-user-privacy-api

## 6. Changelog (https://www.enterpret.com/changelog)
- [FACT] Apr 2026: **Slack rebuilt as event-driven ingestion**, seconds-level delivery, thread preservation, real-time edits/deletes. Older help doc said a 36-hour API cycle (https://helpcenter.enterpret.com/en/articles/6320459-slack-inbound-integration). That is a batch-to-event migration story.
- [FACT] Apr 2026: YouTube comments with 90-day backfill, spam filtering; Zendesk backfill made faster/more complete; Snowflake setup previews columns/rows before commit.
- [FACT] May 2026: **nine user-facing integration status indicators** plus proactive admin email alerts.
- [FACT] Jul-Aug 2026: many new connectors (HubSpot, Pylon, Decagon, Fathom, TikTok, etc.) with flexible field mapping and recurring sync schedules; MCP server v2 with citations; webhook escalation signals.

## Implications for our take-home

Terms to use (their vocabulary):
- "Ingestion layer", "connector/integration", "record" (not "event"), `fileID`/source, "tenant", "taxonomy", "classify once on arrival", "enrichment", "projection", "CDC", "backfill", "completeness, latency, error rate", "per-source error taxonomy", "cost per feedback record", "noisy neighbor", "eventual consistency", "self-healing".

Design choices that mirror them (cheap to justify):
- Accept `id` + source + `type` + `createdAt` (seconds) + typed `metadata`; **idempotent on (tenant, source, id)**: skip duplicates by default, replace-on-same-id as an explicit opt-in, never "append by re-sending".
- Validate strictly and **return per-record errors with a referenceID**; never drop silently (they had a legacy silent-drop problem). 200/202 = accepted, not processed.
- Separate **accept** (fast, durable write) from **enrich/classify** (async), with a queue between. Mention they "classify once, on arrival, against a stable taxonomy".
- Version-based writes: reject stale/out-of-order updates (KOSH rule); use `updated_at`/version on records.
- Partition queues and rate limits **per tenant** (and per source) so a bad tenant cannot clog others; cite their queue-clogging and noisy-neighbor incidents as the reason.
- Payload offload (large bodies to object storage, pointer in queue), batch size cap (100 recommended), 429 with Retry-After, retriable vs non-retriable error classes.
- Backfill as a first-class path distinct from live ingest (lower priority lane, same dedup and taxonomy).
- PII scrub **before** persistence/enrichment; a delete-by-user path with a batched SLA.
- Observability: per-source completeness/latency/error-rate metrics, staleness alerts, status states (healthy/degraded/stale), health check cadence.
- Keep it simple: one repo, thin abstractions, "small designs compound"; say which parts are deliberately not built.

Trade-offs to state out loud: freshness vs write efficiency (their ~15 min batch window); eventual consistency vs multiple read models; schema-on-write flexibility vs wide-table cost; serverless elasticity vs 15 min / 6 MB / cold-start limits; managed service vs portability (they chose one cloud); LLM cost and nondeterminism (constrain with a persistent taxonomy, cache classification by content hash).

Numbers to cite for "what if 10x":
- Their stated scale: hundreds of millions of records/updates per day on the analytical cluster; single customers with 200M+ feedback items; 500-800+ attributes per Account object; 50+ sources.
- Their public API: 2000 RPM x 100 records/batch = up to ~200K records/min ceiling per key; 200 KB/request cap.
- Order-of-magnitude: 300M records/day is about 3.5K records/s average (peak maybe 5-10x). Say 10x would be ~35K/s average; answer = partition by tenant, scale queue consumers, batch writes, move hot read path to a columnar projection, put LLM enrichment on a separate budgeted lane.
- LLM nondeterminism figure for justifying taxonomy-grounded classification: 8-10% count variance between identical runs; churn down 86% with a persistent taxonomy.

Gaps (do not assert): queue tech, Postgres/Kafka use, exact interview format, the "System Design AI Native" round, any founder talk on dedup or incidents. Ask the recruiter or frame answers technology-neutrally with AWS-flavored options (SQS, DynamoDB, S3, Lambda/ECS).
