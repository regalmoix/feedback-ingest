# Enterpret: HM chat (today) and CTO round (tomorrow)

Read sections 1, 4 and 8 before the HM chat. Read everything before the CTO round.
**Honesty rule:** say "your blog says" or "your docs describe". Never say "you do X internally". Leave out any number you can't point to on a public page.

---

## 1. Enterpret in 60 seconds

- **What it does:** the homepage calls it "customer intelligence infrastructure for teams building with AI". *(enterpret.com)*
- **Product loop (homepage headings):**
  - **Unify:** Feedback Integrations, Adaptive Taxonomy, Customer Context Graph, Data Enrichment.
  - **Understand:** Dashboard, AI Insights, MCP Server, Sales Intelligence.
  - **Act:** AI Agents, Close the Loop, Workflow Integrations.
- **Core idea:** the Feb 2026 blog says they classify feedback once, on arrival, against a persistent per-customer taxonomy, so queries become filters. It also argues that stateless LLMs can't count or trend feedback reliably on their own. *(blog: "why customer intelligence requires infrastructure")*
- **Recent launches:**
  - Enterpret 2.0, Oct 2025. Varun's blog line: "Speed without intelligence is not progress. It is chaos."
  - Agent OS beta, Jun 2026: the Enterpret Agent plus Automations that run on a schedule or fire on a signal.
  - Agent Memory, Sep 29.
  - Support QA, Oct 6.
  - Feedback Bench, today (Oct 7).
  - New connectors almost every month *(changelog)*.
- **Who uses it:** Canva, Notion, Figma, ElevenLabs, Wispr Flow, Strava, Hinge, Apollo.io, Descript, Perplexity *(customers page)*.
- **Stage:** $20.8M Series A in Dec 2024, led by Canaan; about $25M raised in total *(TechCrunch)*. Third-party trackers estimate roughly 70-80 people. All six open engineering roles are in Bengaluru.
  - Don't name a funding stage yourself. One job posting says "Series-B", but no round has been announced.
- **Founders:** brothers, founded 2020.
  - **Varun (CEO):** customer success at LinkedIn, then Amplitude (employee #15), then Head of Enterprise Customer Ops at Scale AI.
  - **Arnav (CTO):** researcher at IIIT-H's language-technology lab (LTRC, 2014-16), then Uber from SWE to Senior SWE (2016-20). Forbes 30 Under 30 Asia 2023.
- **Founding insight (Varun):** teams tracked funnels "to the decimal" but couldn't name why customers were unhappy. The why was buried in unstructured feedback.
- **Your link to it:** your take-home was the Unify stage: connectors, a uniform record, idempotency and replay.

---

## 2. Culture signals and how to show fit

The careers page lists 3 values and 3 principles, and the engineering postings repeat them. **Don't recite the names. Let a story show each one.**

| Signal | Evidence | Story to bring |
|---|---|---|
| **Be an Owner, Not a Renter** | Careers page; postings ask for a "deep sense of ownership" and on-call for your area | Something nobody assigned you that you picked up, shipped and ran in prod. [YOUR STORY] |
| **Care Personally, Challenge Directly** | "We give and ask for direct and actionable feedback" | A time you pushed back with data (benchmark, logs, prototype), then committed either way. [YOUR STORY] |
| **Humble Growth Mindset** | Varun: culture rests on "great people and humility" | A real mistake you owned in public, and the systemic fix that followed (test, alert, rule). [YOUR STORY] |
| **Seek Truth** ("Opinions are starting points, not facts") | Careers page | A debugging story told in order: hypothesis, evidence, root cause, fix. [YOUR STORY] |
| **Narrow the Focus, Up the Intensity** | Careers page | A time you cut scope, not quality, to ship. Take-home example: SQLite, tight scope, and a debt ledger of known gaps. |
| **Ambition Shapes Reality** | Careers page | A goal that forced you to rethink the approach. [YOUR STORY] |
| **AI-native working style** | MTS Platform posting: use AI tools "to move much faster while validating outputs" | Your real workflow: which tools, where AI helps, how you verify its output (tests and gates), and one time you caught it wrong. |
| **Boring tech, small designs** | Eng blog: "simplicity over cleverness", "Small designs compound over time" | A time you chose the simple design on purpose, and what you left out. |
| **High velocity** | Glassdoor snippets (4.7/5 from 18 reviews): "great peers with steep learning curve", "high velocity startup might not be everyone's cup of tea" | Say you want that pace and are choosing it knowingly. |

---

## 3. The CTO (Arnav): what he likely cares about

- **He was an IC engineer before co-founding.** He spent about four years at Uber and reached Senior SWE. Expect him to dig 3-4 levels into a CV project, so pick work you can defend down to the details.
- **NLP research background.** He co-authored a 2016 paper on code-mixed social media text, so messy user-generated text is familiar ground for him. Your take-home's community and review-style sources touch exactly that kind of data.
- **Evidence over claims.** He wrote the 2024 Wisdom launch post, which stresses insights backed by real customer quotes. In 2022 he wrote "All product decisions are bets". Give a number for every claim and say how you knew the system was correct.
- **His team's public engineering style:** start on Lambda, then move services to ECS or Batch when needed; keep costs down; evolve the design rather than rewrite it. The blog says the Blackhole ingestion system grew to 50+ integrations "without a single rewrite".
- **He runs a flat team.** A Dec 2025 posting for a Head of Engineering reporting to him described a "flat team of ~20 engineers" and asked to "establish regular customer interaction for all engineers". Show that you need little managing.
- **What this means for your answers:** put correctness and trade-offs before scale, be honest about limits, and make simple choices you can explain.
- *(Unverified, do not say:)* any specific Uber team he worked on.

---

## 4. HM chat (15 min, informal)

Keep each answer to 60-90 seconds and leave 3-4 minutes for your questions. Speak from bullet points, not a script.

**Q1. Tell me about yourself.**
- [X years] in backend. One line on the scale or reliability work you've owned. One line on why you want a smaller AI-native team now.
- Don't: walk through your CV year by year.

**Q2. Why are you leaving?**
- Frame it as moving toward something: "I've learnt [scale, process, X] at a larger company. Next I want a small team where one engineer owns a bigger slice, closer to customer impact, on a product where the data pipeline *is* the product."
- Don't: mention your manager, pay, politics or layoffs, or say "just exploring". Don't name your employer or describe its internals.

**Q3. Why Enterpret?** Short version here; the full one is in 5b.
- Three points: the problem (feedback scattered across 50+ sources), your hands-on link (the take-home was Unify), and the stage (small team, big ownership).
- Don't: say "AI is the future" or "great funding", or anything you could say about any startup.

**Q4. What are you looking for next?**
- Ownership from design through on-call, more contact with customers, and a lot to learn.
- Don't: lead with title, a manager track or remote work.

**Q5. How do you handle ambiguity?**
- Clarify with the user or PM, write a one-pager, ship a small first milestone, then iterate. Give one real example.
- Don't: say "I wait for clear requirements."

**Q6. How do you use AI tools?**
- Plan, generate, review, and let the tests decide. AI does search and boilerplate; you make the design calls. Give one example of catching it wrong.
- Don't: say "AI wrote it, I glued it" or "I don't really use AI".

**Q7. Onsite in Bengaluru, notice period, compensation?**
- Onsite: "I'm comfortable in the office." Ask what the weekly rhythm is; the postings say "Onsite" but the benefits list a hybrid setup.
- Notice period: state it plainly, plus any flexibility you have.
- Compensation: "I've shared it with [recruiter], and I'm sure we'll land on something fair."
- Don't: negotiate here.

**Q8. Any questions for me?** See section 7.

---

## 5. CTO round (45 min)

### 5a. "What's the most complex technical problem you've worked on, and why is it complex?"
**Structure (about 3 min, then expect follow-up questions):**
1. Context in one line. [YOUR STORY: the system, your role, its scale in numbers]
2. **Why it was complex.** Name the actual constraints: correctness, concurrency, ordering, scale, legacy code, unclear requirements, other teams. This is the part he asked about, so spend the most time here.
3. The 2-3 options you weighed, and the trade-off of each.
4. What you chose and why, including what you deliberately did **not** build.
5. What broke or surprised you, and how you found out (evidence, not hunches).
6. The result, in numbers.
7. Reflection: what you'd do differently.

**What will convince him:**
- Say "I" for your own decisions and "we" for the team's.
- Name specific failure modes ("on retry the same event was counted twice, because...").
- State the invariants and how you checked them.
- Be honest about limits.

**Don't:**
- Pick a project where you were on the edge of the work.
- Claim scale you can't defend.
- Use internal codenames or reveal your employer's internals. Describe it generically, e.g. "a high-volume event pipeline".

### 5b. "Why Enterpret? What excites you?" Three real hooks
1. **The hard part is infrastructure, not one LLM call.** Their Feb 2026 blog tested eight frontier models: even the most consistent left about 60% of its themes unmatched between identical runs, and a persistent taxonomy cut run-to-run churn by about 86%. That's backend and data work, which is what you enjoy.
2. **You've already built a slice of it and liked it.** The take-home was Unify. Agents such as Quality Monitor, Escalation Shield and Automations are only as good as the records underneath them: a burst of duplicates or a late batch shows up as a false spike.
3. **Stage and customers.** It's a small team where you can grow from owning a component to owning a larger area (the MTS Platform posting promises "a clear path from owning components to shaping larger slices"). You use some of the customers' products yourself: Notion, Canva, Figma.
- Optional tie-in to Varun's founding insight: analytics tells you *what* happened, feedback tells you *why*. You want to build the layer that lets people query the *why*.

### 5c. "What have you learnt about our product?" (30-second answer)
> "Enterpret runs a loop: Unify, Understand, Act. Unify brings in 50+ sources, plus a webhook API, warehouse sync and CSV, and classifies each item on arrival into the customer's own taxonomy: keywords for *what*, themes for *why*, and four categories (complaint, help, improvement, praise). Understand puts that in front of people through AI Insights, dashboards and the MCP server, with citations back to the source. Act is agents like Escalation Shield and Quality Monitor, pushes to Jira, Linear and Slack, and now Agent OS automations. My take-home was the Unify stage: push webhooks and pull connectors into one record, with idempotency and replay. One thing in your public webhook doc stood out: a repeated id is skipped by default, and a 200 can still mean records don't show up. I ended up making a similar split between accepted and processed."
- Then ask one open question (section 7).
- Say plainly that you didn't build Understand or Act.

### 5d. Other likely CTO questions

**Walk me through [CV project X].**
- The problem, your part, the trade-offs, and one number. Expect "why not Y?"
- Don't: hand-wave the details you skip.

**What would you do next on the take-home?**
- In order: PII redaction before storage (their integrations page says PII is obfuscated before ingestion), then a per-tenant rate limit, then fair queueing across tenants.
- Don't: pretend it was complete.

**Tell me about a mistake.**
- Real impact, owned publicly, a systemic fix, and evidence the fix held.
- Don't: humblebrag or blame others.

**Tell me about a disagreement.**
- You raised it privately, with data, and listened to their constraints. Then you either persuaded them or disagreed and committed.
- Don't: frame it as "I was right", or escalate first.

**Speed or quality?**
- It depends on how reversible the decision is. Move fast on easy-to-undo changes (feature flags, small PRs). Be careful with hard-to-undo ones: data models, public contracts, anything that can lose data. The Staff Platform posting talks about "hard-to-reverse decisions".
- Don't: say "quality always" or "move fast and break things".

**An incident you owned?**
- The incident, then the lasting fix (alert, runbook, design change). The MTS posting asks you to turn "recurring failures into durable fixes, not patches".
- Don't: stop the story at the hotfix.

**Where do you see yourself in 2-3 years?**
- Owning a platform area end to end (ingestion reliability, for example), being the person others go to for it, and mentoring.
- Don't: say "manager in a year" or "starting my own company".

**Can't customers just paste their tickets into ChatGPT?**
- Counts and trends need stable definitions and a durable record. ElevenLabs' case study says their LLM-only internal tool "worked well enough to summarize reviews, but not well enough to prioritize".
- Don't: dismiss LLMs. They ship Claude and GPT models inside the product.

---

## 6. The two nits: own them honestly, then say what you're doing about them

**Nit 1: "Not much direct customer exposure"**
- Own it: "That's fair. Most of my customer contact has come second-hand, through PMs, support escalations and incidents, not direct calls." Then give one real example where you read raw tickets or logs to understand a user. [YOUR STORY]
- What changes it: the product exists to bring the customer's voice to engineers. In the Wispr Flow case study, their VP of Engineering joined the Quality Monitor Slack channel. "I'd be building that pipeline and using it myself, and I'd want to sit in on customer calls early."
- Don't: say "I prefer to stay in the backend", or claim customer exposure you don't have.

**Nit 2: "No very large end-to-end project"**
- Own it: "I've owned components end to end, from design through prod and on-call [example], but not a multi-quarter, multi-team system."
- What changes it: "That's a big part of why I want a small team where component owners grow into owning larger areas. The take-home is a small piece of evidence: I designed, built, tested and demoed a whole ingestion path in days. It isn't proof at scale."
- Show you know how to break big work down: thin slices, each one shippable.
- Don't: inflate a team project into "I led it", or get defensive.
- **Don't raise either nit unprompted in the HM chat.** Just have the answers ready.

---

## 7. Questions to ask

**HM (pick 2):**
1. Is this role on Platform or Core Product, and what is that team focused on this quarter?
2. How do engineers here hear from customers today? Do they join calls or watch agent channels?
3. What does a great first 90 days look like? The MTS posting mentions 90-day, 6-month and 12-month milestones.
4. What separates engineers who do well here from those who struggle?
5. What's the in-office rhythm in Bengaluru?
6. Is there anything from my take-home you'd want me to work on?

**CTO (pick 2-3):**
1. As connectors and Agent OS automations multiply, where does ingestion hurt most today: freshness, completeness or cost per record?
2. Your KOSH post mentions a roughly 15-minute freshness window on the analytics side. Do signal-fired automations make that a constraint?
3. Blackhole reached 50+ integrations without a rewrite. Over those years, how did the line between connector code and platform code move?
4. Slack moved to event-driven ingestion in April. Is moving from batch to events the plan for other connectors too?
5. With external MCP clients querying the graph, how do you think about tenant scoping and query cost?
6. What's the most important problem you'd want me to solve if I joined?

Don't ask anything the website already answers, and don't open with perks.

---

## 8. Don'ts and landmines

- Don't name or criticise your current employer, or describe its internals.
- Don't claim a Series B, an exact headcount, or "Canva 220M" (that figure may be a user count).
- Don't say "you use Kafka/Postgres/Redis". It isn't public, so ask instead.
- Don't mention Arnav's LinkedIn, or any details of his Uber team.
- Don't misstate the Wispr Flow story: the two regressions were caught in a five-day trial sprint, before Quality Monitor existed.
- Don't say "Canva's Close the Loop automates bug dedup". Close the Loop is Canva's own programme, which uses the MCP server to check whether another team already owns a flagged bug.
- Don't recite value names, marketing copy or memorised answers.
- Don't critique their stack choices (Go, Lambda) unless asked, and offer a suggestion if you do.
- Don't overclaim the take-home. Say "the same decision, at much smaller scale".
- Don't bring up compensation, perks or competing offers with the HM or CTO.
- Don't give the years-of-experience figure from memory. Check it against the CV first; the MTS posting asks for 6+.

---

## 9. Sources
- enterpret.com · /careers · /changelog · /customers · /platform/feedback-integration
- enterpret.com/blog/enterpret-2-the-foundation-for-customer-intelligence
- enterpret.com/blog/why-customer-intelligence-requires-infrastructure-not-just-ai
- enterpret.com/blog/introducing-agent-os-proactive-customer-intelligence-automations
- enterpret.com/blog/wisdom-ai-copilot-for-customer-insights · /blog/enterpret-series-a
- enterpret.com/customers/wispr-flow-enterpret-how-a-support-team-became-engineerings-frontline · /customers/canva
- enterpret.com/customers/how-elevenlabs-outgrew-internal-solutions-to-turn-customer-feedback-into-product-decisions
- engineering.enterpret.com/the-unorthodox-path-how-we-built-enterpret-5/
- engineering.enterpret.com/kosh-the-knowledge-graphs-that-power-enterpret/
- helpcenter.enterpret.com/en/articles/12131693-webhook-integration · /12665751-what-is-the-taxonomy
- job-boards.greenhouse.io/enterpret (jobs 7915008003, 7915246003, 7821474003)
- builtinbengaluru.in/job/head-engineering/6903140
- techcrunch.com/2024/12/04/enterpret-automatically-extracts-insights-from-customer-feedback
- news.aakashg.com/p/how-enterpret-grows-the-deep-dive · pmreimagined.substack.com/p/build-better-products-with-customer
- forbes.com/profile/arnav-sharma · affluense.ai/profile/arnav-sharma-enterpret-f4511d
- glassdoor.com/Reviews/Enterpret-Reviews-E6020935.htm (snippets only)
- techinterviewhandbook.org/behavioral-interview · /final-questions

🟡 Fill the [YOUR STORY] placeholders once the CV is shared
