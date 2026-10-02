# Enterpret: customers, personas, use cases (research notes)

Researched 2026-10-03 from public pages only. Fact = sourced bullet. **[Inference]** = my reading, not stated by Enterpret.
Caveat: WebFetch summarises pages through a small model; numbers below were not re-verified on the raw page. Capterra/Gartner/some pages returned 403/404.

## 1. Named customers and case studies

Customer index (https://www.enterpret.com/customers; homepage https://www.enterpret.com/): Canva, Notion, Apollo.io, Bitvavo, Descript, Feeld, Atlassian, ElevenLabs, Zapier, Western Union, Fanatics, The Farmers Dog, Strava, Hinge, Kit, Philo, Wispr Flow, Memrise, The Browser Company, Boll and Branch, Figma, Vimeo, Samsung Food, Loom.

| Customer | Sources connected | Who | Outcome / number | URL |
|---|---|---|---|---|
| Canva | support, social, surveys, in-product feedback; 100+ languages | product teams, accessibility eng, "Close the Loop" feedback ops, Insights Ops lead; 200+ employees with access | millions of feedback items/yr; 20,000+ searches in 6 months; hundreds of thousands of survey responses analysed in hours instead of months; weekly accessibility digest via MCP; cross-checks bugs against existing Jira tickets | https://www.enterpret.com/customers/canva |
| Notion | Intercom tickets, app store reviews, X/Twitter, Slack, community forums | VP CX, Head of Product Ops, product ops specialist, PMs, eng | monthly VoC report 2 weeks to 3 days; replaced 700+ manual tags over tens of thousands of monthly tickets; login-issue theme got dedicated eng time; "80% faster insight-to-decision" (homepage) | https://www.enterpret.com/customers/notion |
| Apollo.io | feedback surveys, support chat, cancellation surveys, customer interviews, funnel/usage analytics | CPO, product, eng, support | 40% fewer support tickets / human inquiries; "9x growth"; issues split 40% bugs/UX, 40% education, 20% need a human; prioritises by ARR; segments by persona, title, location | https://www.enterpret.com/customers/apollo |
| Descript | 15+ sources: Zendesk, Grain sales calls, surveys, Amplitude | User Research Lead, Director of Support | 83% faster research synthesis (1 day to 30 min); asks "which browsers/versions cause performance issues?" and "how did an A/B test affect adoption?" | https://www.enterpret.com/customers/descript |
| Memrise | Zendesk, SurveyMonkey, App Store + Google Play reviews, Reddit, interviews | support specialist, UX lead | 71% drop in reset-progress tickets after the feature shipped; 240+ hours/yr saved; Slack reports replace 2.5 days/month manual work; 65M users, 189 countries | https://www.enterpret.com/customers/memrise |
| The Browser Company (Arc) | member feedback, support/feature requests, performance reports, mobile + desktop analytics, Windows beta feedback | Membership Lead, research, perf monitoring, Windows product support lead, eng | weekly "Member Pulse" report to all teams; anomaly detection; RAM/CPU spikes "between versions"; bulk-notify users when their request ships; day-one mobile retention issue | https://www.enterpret.com/customers/the-browser-company |
| ElevenLabs | app stores, support tickets, social, Slack delivery | lean product team | LLM-only attempt gave fine summaries but poor prioritisation; found real monetisation issue was credit-consumption clarity, not price (credit warnings, one-time credit packs for underserved regions); mobile app $0 to $10M ARR in under 6 months; weekly digest replaced 30-45 min Monday prep | https://www.enterpret.com/customers/how-elevenlabs-outgrew-internal-solutions-to-turn-customer-feedback-into-product-decisions |
| Wispr Flow | support tickets (5,000+/week, 104 languages, Mac/Windows/iOS/Android) | Founding Head of CX, support engineers, CTO | Quality Monitor Agent: alert with plain-language summary, sample tickets, build version, cross-version impact, trend state (emerging/spiking/stable/declining), reliability area. 73,000+ tickets structured; 5-day rollout caught 2 regressions; spike detected before CEO forwarded an angry email; previously a spreadsheet of patterns | https://www.enterpret.com/customers/wispr-flow-enterpret-how-a-support-team-became-engineerings-frontline |
| Philo | Salesforce cases, Amazon Connect calls, app reviews, social, CSAT | support leader | spent first weeks pruning taxonomy to match customer wording; analysed contact topics by time-of-day interval, cut overnight support hours, ~$1M/yr; quality monitoring flagged billing issues hours/days earlier than weekly reports; feature-launch sentiment 82% positive; 24 users across 6 teams by month 2 | https://www.enterpret.com/customers/philo-enterpret-the-1m-question-no-one-thought-to-ask |

Other: Kit, Bitvavo, Feeld, Boll and Branch, Figma stories exist on the index but I could not fetch them. Funding/context: $20.8M Series A, customers incl. Canva and Monday.com (https://techcrunch.com/2024/12/04/enterpret-automatically-extracts-insights-from-customer-feedback). Platform ingests sales calls, tickets, surveys, X threads, app reviews, product usage, revenue data; includes PII scrubbing rules (same TechCrunch URL). Help center claims 50+ source types (https://helpcenter.enterpret.com/en/articles/12665465-enterpret-features-explained).

## 2. Reviews, complaints, feature requests

- G2: 4.5/5 from 111 reviews (https://ai.g2.com/product/enterpret-inc-enterpret; reviews page https://www.g2.com/products/enterpret-inc-enterpret/reviews returned 403 to direct fetch). Praise: Wisdom (ask a question, get a summarised answer with real examples), one place for feedback, strong support.
- G2 complaint tags (counts per search snippet): Integration Issues (10), Steep Learning Curve (9), Difficult Setup (9), Inaccuracy (8), Filtering Issues (8). Also: slow loads/errors, mobile UI lacks desktop parity, taxonomy needs ongoing attention, price high for early-stage, some say competitors do thematic analysis better (via search summary of G2).
- G2 summary specifically: friction "connecting all required sources and mapping customer metadata"; missing connectors for newer adjacent tools slow time-to-value.
- Capterra: 4.8/5 from 6 users; ease 4.2, support 4.2, value for money 3.6, features 4.7; usage-based pricing (https://www.capterra.co.uk/software/1037555/enterpret). Praise for Slack delivery and self-serve without analysts.
- AWS Marketplace reviews (https://aws.amazon.com/marketplace/reviews/reviews-list/prodview-qyqphrdnaafd6): cons are AI accuracy needing initial refinement, ongoing taxonomy maintenance, integration setup and data mapping effort, steep onboarding, UI initially overwhelming, limited cross-tool integration. Use cases: moving off spreadsheet tagging, understanding frustration drivers across channels, Slack alerts for emerging issues.
- Founder interview lists data-quality problems: irrelevant patterns, standardisation across sources, multiple languages and formats, duplicate or noisy feedback (https://pmreimagined.substack.com/p/build-better-products-with-customer).
- **[Inference]** Hard problems that show up repeatedly and are good to demo handling: (a) metadata mapping per source (version, plan, country arrive inconsistently), (b) taxonomy drift/overlap needing merge, (c) noisy/duplicate items inflating counts, (d) multilingual text, (e) slow or partial ingestion making "now" stale, (f) false-positive spikes eroding eng trust (Wispr: "accuracy over speed").

## 3. Personas and the questions they ask

Personas on the site (https://www.enterpret.com/solutions/customer-experience): CX leaders and support ops (churn, ticket volume), product managers (roadmap from demand), GTM/sales (deal blockers, churn risk). Case studies add: Product Ops (Notion), User Research (Descript), Insights Ops (Canva), CPO (Apollo), Membership/Community Lead and perf engineer (Browser Co), Head of CX (Wispr), support leader (Philo), accessibility engineer (Canva).

Questions, from Wisdom docs and cases:
- "What are the top complaints about Login this quarter? Include citations." / sentiment change over six months / which segments are most frustrated (https://helpcenter.enterpret.com/en/articles/9711115-wisdom-prompt-examples and the Wisdom search results)
- "Top feature requests from enterprise customers this quarter?"; "Why are users churning in the mobile app?"; "Complaints blocking deals?"; "Sentiment on checkout flow month over month?"
- Persistent filter rule: "Always filter feedback to enterprise customers only."
- By version: "Which browsers/versions cause performance issues?" (Descript); "Which performance issues are spiking between versions?" (Browser Co).
- By release: "Did the fix reduce tickets?" (Memrise 71%); feature-launch sentiment (Philo 82% positive).
- By country/segment: persona, title, location (Apollo); underserved regions (ElevenLabs); country standardisation is a built-in enrichment.
- By plan/account: filter by account ARR and plan type for enterprise pain (https://www.enterpret.com/changelog/october-2025-product-highlights).
- By time of day (Philo).
- "Are potential bugs already being addressed by other teams?" (Canva, vs Jira).

## 4. Marketed use cases

- Release/launch measurement: "Measuring whether product launches and fixes actually improved outcomes" (homepage).
- Bug/regression surfacing: Quality Monitor listens to all feeds, flags statistically significant spikes, scores severity/relevance, drafts an RCA, posts to Slack/email with feedback count and trend chart, and updates existing alerts rather than duplicating (https://helpcenter.enterpret.com/en/articles/10766163-agent-quality-monitor). Setup: optional feedback filter + required destination.
- Escalation Shield / Escalation agent: emotionally intense, high-risk feedback from strategic accounts. Newsfeed agent: personalised trend digests (https://helpcenter.enterpret.com/en/articles/12665465-enterpret-features-explained).
- Roadmap prioritisation: rank by revenue/ARR impact, not mention count ("most frequent does not equal highest churn risk").
- Churn signals: repeat contacts, escalations, CSAT, cancellation reasons.
- Support deflection: Apollo 40%, Memrise 71%, Philo staffing.
- Close the loop: notify users when requests ship (Browser Co, Canva).
- Product area dashboard: "Track Your Feature" template, filter by taxonomy L1/L2/L3, 12-month trend, scheduled Slack/email report (https://helpcenter.enterpret.com/en/articles/8906705-how-do-i-monitor-feedback-for-my-product-area).
- Taxonomy: three-level hierarchy plus themes/subthemes, detects and merges overlapping topics. Categories: Help, Improvement, Complaint, Praise. Enrichments: sentiment, response time, country standardisation, timestamp conversion.
- Knowledge Graph links feedback to accounts, users, opportunities, products. Agent product runs sessions plus scheduled automations, cites sources, "will not invent a number, a quote, or a link" (https://helpcenter.enterpret.com/en/articles/15608623-getting-started-with-enterpret-agent).

## 5. Public demo scenario

No single repeated demo company found. Closest recurring shapes: (1) the Wispr "spike caught before the CEO's email" narrative, (2) "a regression shows up between versions" (Browser Co, Descript), (3) "a metadata slice (time of day, plan, region) changes a decision" (Philo, ElevenLabs). **[Inference]** A tenant-per-customer story fits their multi-tenant SaaS positioning.

## Implications for our take-home

### Realistic two-tenant demo story (synthetic)

- **Tenant A: "Lumenote" (consumer note/voice app, mobile + desktop, ~5k tickets/week).** Sources: support tickets (Zendesk-like), App Store + Play reviews, Reddit/X, in-app feedback. Metadata filters that matter: `app_version`/build, `platform` (iOS/Android/Mac/Windows), `country`, `language`, `plan` (free/pro), `source`, `created_at`. Languages: en, de, ja, pt-BR, es. Personas: Head of CX, PM, performance eng.
- **Tenant B: "Brightwave" (B2B workflow SaaS, enterprise accounts).** Sources: Intercom-style chat, sales call notes, NPS/CSAT surveys, community forum. Metadata: `plan` (team/enterprise), `account_arr_band`, `region`, `product_area`, `release`. Personas: Product Ops, CPO, CS lead.
- Keep tenants isolated (own taxonomy, own metadata schema, different field names for same concept) to echo the "mapping customer metadata" complaint.
- Inject realistic mess: duplicate tickets (same issue emailed and reviewed), tickets missing version/country, mixed languages, late-arriving backfill, spam/noise reviews, a taxonomy with near-duplicate themes ("login fail" vs "cannot sign in").

### Three firefight scenarios (as the customer would report them)

1. **Post-release regression (Lumenote, Head of CX):** "Since build 4.12 shipped Tuesday, tickets saying dictation stops mid-sentence on Windows are spiking, mostly pro plan, but the version field is blank on half of them. Is this a real regression or noise, and which builds?" Tests: spike detection vs baseline, version null-handling, dedupe, platform slice, alert with samples.
2. **Regional billing/credit confusion (Lumenote or Brightwave, PM):** "German and Brazilian users are complaining they got charged after running out of credits; it is mostly 1-star app reviews, some in Portuguese. Is it a pricing problem or a clarity problem, and is it only one country?" (echoes ElevenLabs). Tests: multilingual grouping, country standardisation, review vs ticket mix, fix measurement after a release.
3. **Enterprise churn signal (Brightwave, Product Ops/CS lead):** "Three enterprise accounts raised SSO login failures in chat and on calls this week; do these map to the 'Login' theme, how many distinct accounts versus repeat messages, and did last release's fix reduce them?" Tests: account-level dedupe (distinct accounts not mentions), plan/ARR filter, cross-source grouping, before/after release comparison, escalation alert.

### Vocabulary to reuse

feedback record/item, source, tenant, taxonomy (L1 domain / L2 feature area / L3 topic), theme/subtheme, category (Help, Improvement, Complaint, Praise), sentiment, enrichment, metadata/custom fields, spike/anomaly, trend state (emerging, spiking, stable, declining), severity and relevance, root-cause summary (RCA), reliability area, build version, regression, quality monitor, escalation, newsfeed/digest, saved report, dashboard, rule/filter, citations/evidence, "close the loop", "voice of customer (VoC)", "customer knowledge graph", "insight-to-decision", "noise vs signal".
