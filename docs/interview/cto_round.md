# CTO round game plan (Arnav, 45 min, cultural)

Built from your CV and the HM call. Lines marked **[fill]** need a detail only you know: decide it before the call
and don't invent it in the room. Arnav was a senior engineer at Uber, so expect him to dig 3-4 levels into one
project.

---

## 1. Your 60-second intro

> "I'm a senior backend engineer, about 4 years in, all of it at one AI HR-tech company. For the last two years
> I've built and scaled an **autonomous voice interviewing agent**: it runs screening, coding and system-design
> interviews and grades them with LLMs against competency rubrics. It has run for 56.8K candidates across 16
> enterprise customers. I also built its real-time proctoring, the RAG memory layer for our agent framework, and a
> zero-downtime storage migration that cut session-read latency by about 90%. I want to go deeper as an IC on
> agent infrastructure (quality, latency and cost), on a team where that *is* the product. That's what Abhay
> described here."

Don't: walk through the CV year by year, or name the employer's internal codenames.

---

## 2. Your three stories (pick by the question)

### Story A: the AI Interviewer. Use for "most complex problem", agents, quality, latency, cost

**One line:** an autonomous voice agent (ElevenLabs + LiveKit) that runs interviews and grades them with LLMs; 72.5K
invites, 56.8K candidates, 2.4K roles, 16 enterprise customers, 32.4K auto-generated feedback reports (97.9%),
5,335 recruiter-days saved, 4.3/5 satisfaction.

**Why it's complex** (spend most of your time here): it's four hard problems at once.
1. **Real-time latency.** A voice turn must feel human: speech-to-text, then LLM, then text-to-speech, inside a short
   budget. Interruptions, silence and turn-taking are hard. [fill: your turn-latency target, what dominated it, and what you did]
2. **Grading quality.** LLM scores must be consistent and fair across candidates. A recruiter makes hiring decisions on
   them. [fill: how you measured consistency, e.g. rubric design, structured outputs, calibration against human graders, re-runs]
3. **Reliability at scale, with no retries for the human.** A candidate can't redo an interview because a call
   dropped. [fill: failure modes you handled: reconnects, partial transcripts, provider outages]
4. **Cost per interview,** across voice minutes and LLM tokens, sold to enterprise customers. [fill: cost levers you used or measured]

**Trade-offs to name:** [fill 2: e.g. which model for live turns vs offline grading, streaming vs batch grading, how much
the agent may improvise vs follow a script]

**Result:** the numbers above. **Reflection:** [fill: what you'd do differently, e.g. "build the evaluation harness earlier"]

**Bridge to Enterpret:** "Abhay said your next goals are quality rubrics, turn latency and cost per automation.
That's the same triangle I've been working in. I've seen how a rubric-graded LLM output earns or loses user trust."

### Story B: the zero-downtime S3 to RDS migration. Use for "complex" if he wants data or systems depth, or for ownership

**One line:** moved interview session storage from blob wrappers on S3 to transactional, queryable RDS state, with no
downtime: 56 PRs, net -8.2K lines of code, a gated rollout with backfills and forward/backward compatibility.
Session-read latency fell about 90% and on-call load dropped.

**Why it's complex:**
- **Live traffic during the move:** interviews were running while you migrated.
- **Two sources of truth:** dual-write or read-fallback windows, so old and new code can both run.
- **Backfill correctness:** how you proved every session was copied exactly. [fill: verification method, e.g. checksums or shadow reads]
- **Rollback at every step.** [fill: the stages: dual-write, shadow-read, flip reads, stop writes, delete legacy]

**Why it lands with Arnav:** it's "evolve, don't rewrite", shipped safely in small steps, with a deletion-heavy diff,
the same instinct as his team's "50+ integrations without a single rewrite".

### Story C: performance and truth-seeking. Use for "debugging", "seek truth" or "impact"
- **Performance:** you sped up core methods of a workforce product by 1000x, cutting endpoint latency by about 10 ms.
  [fill: what was slow (N+1 queries? repeated work?), how you found it (profiler?), and the fix]
- **Security:** you fixed 10+ vulnerabilities (BFLA, CSRF, privilege escalation) in the interview APIs. [fill: did you find
  them yourself, or were they assigned? If you found them, that's an ownership story]

---

## 3. Map stories to their values

| Their value | Your evidence |
|---|---|
| **Owner, not renter** | The storage migration (you led it end to end and cut on-call). Rolling out Ruff and MyPy in CI. [fill: any security fixes you found yourself] |
| **Seek truth** | The 1000x speed-up: profile, find the cause, measure. Measuring grading consistency. |
| **Narrow the focus, up the intensity** | The migration was shipped in gated steps, not a big-bang rewrite. The take-home: tight scope plus a debt ledger. |
| **Care personally, challenge directly** | [fill: a time you pushed back with data, e.g. on grading quality or a risky rollout] |
| **Humble growth mindset** | [fill: a real mistake and the lasting fix] |
| **AI-native** | You ship agents for a living. You taught an AI Agents workshop (OpenAI Agents SDK + MCP) to 150+ people at IIT BHU. The take-home was built with an AI-agent workflow and strict gates (ruff, mypy, pytest). |
| **Customer closeness** | 4 US go-lives worth $10M+, and 16 enterprise customers on the AI Interviewer. [fill: did you join customer calls?] |

---

## 4. The two nits, now with your evidence

**"Little customer exposure at the edge"**
- Honest version: "Most of my customer contact came through PMs and go-lives, not daily direct calls."
- Evidence it isn't zero: you led **4 US unemployment-exchange go-lives ($10M+ revenue)**, and the AI Interviewer
  served **16 enterprise customers** with a 4.3/5 satisfaction score. [fill: one moment where customer feedback changed what you built]
- Why this role fixes it: "Abhay mentioned engineers sit in shared Slack channels with customers. That's exactly
  the exposure I want."

**"No extremely big end-to-end project"**
- Honest version: "My largest was the AI Interviewer: I built and scaled it from [fill: early stage] to 56.8K
  candidates, and the 56-PR storage migration. Neither is a multi-year, multi-team platform."
- Why this role fixes it: "At about 100 PRs a week as a team, with a clear L4-to-L5 path, I'd grow into owning a
  larger platform slice faster than I could where I am."
- Don't: inflate "we" into "I led it".

---

## 5. Why Enterpret: say it in your own words

1. **Their platform problem is my problem.** Agent quality rubrics, turn latency, and cost per automation ($4 to $1).
   I've lived that triangle with the AI Interviewer, and the credits model makes cost work directly valuable.
2. **Customer intelligence is a real, durable problem.** Analytics tells you *what* happened; feedback tells you *why*.
   Their blog shows that stateless LLMs can't count or trend feedback consistently. Infrastructure is the moat, and I
   like building infrastructure.
3. **Velocity and growth.** A small, flat, AI-native team shipping about 100 PRs a week, with a CTO who still codes and an
   IC track to L5. Plus the take-home: building Unify made the problem concrete.

Don't: "AI is the future", "great funding", or anything that fits any startup.

---

## 6. Discussion points to bring up (shows you've thought about their problems)

**Cutting agent cost (the $4 to $1 automation)**
- **Measure first:** attribute tokens per step, per tool call and per automation. You can't cut what you can't see.
- **Prompt hygiene:** trim system prompts and tool schemas, and cache stable prompt prefixes (prompt caching).
- **Model routing:** a small or open-weight model for routine steps, a frontier model only where needed. They already
  self-host fine-tuned models for inference.
- **Non-interactive means batchable:** automations aren't latency-bound, so use batch APIs, run off-peak, and dedupe
  repeated work across runs.
- **Structured outputs and early exit:** stop once the answer is found, and avoid retries caused by malformed output.
- **Guardrail:** every cut must hold quality, so cost work needs the eval harness first.

**Measuring agent quality**
- Rubrics per task type, with LLM-as-judge **calibrated against a human-labelled set** (your AI Interviewer
  experience). Track judge agreement over time.
- Offline evals on a fixed benchmark before each model or prompt change; online signals (user edits, thumbs, reruns)
  after.
- Their **Feedback Bench** launch (Oct 7) suggests they're investing here. Ask about it.

**Model choice without asking the user**
- Route by task type first (cheap, predictable). Then learn from outcomes per task (cost vs quality score). Keep a
  user override.

---

## 7. Likely questions from Arnav (with your angle)

| Question | Your angle | Don't |
|---|---|---|
| Most complex problem, and why? | Story A (or B); spend the most time on *why* | Pick something you can't defend 3 levels deep |
| Walk me through [CV bullet] | Problem, your part, trade-offs, a number | Hand-wave the parts you didn't do |
| How do you know the LLM grading is good? | Rubrics, structured output, human calibration, consistency re-runs [fill] | "The LLM is pretty accurate" |
| How do you use AI tools? | Daily: agents for code with strict gates; you own design and review; one time you caught it wrong [fill] | "AI writes it, I glue it" |
| What did you learn about our product? | Unify, Understand, Act; your take-home was Unify; the agent and automation push; Abhay's cost/quality points | Overclaim internals |
| Why leave now? | Towards: depth as an IC on agent infra, closer to customers, a smaller fast team | Anything negative about your employer |
| A mistake you made | Real impact, owned, systemic fix [fill] | A humblebrag |
| A disagreement | With data, privately, then commit [fill] | "I was right" |
| Where in 2-3 years? | L5-level IC owning an agent-platform area, mentoring | "Manager soon" or "my own startup" |

---

## 8. Questions to ask Arnav (pick 3)

1. "How do you measure agent quality today: rubrics, LLM judges, customer signals? What's still missing?"
2. "For non-interactive automations, where does the money actually go: prompt size, retries or model choice?"
3. "You moved inference to fine-tuned open-weight models. What drove it, and what was hardest about self-hosting?"
4. "Choosing the model automatically per task: route by task type, or learn from outcomes?"
5. "At 10x growth, what breaks first: ingestion, inference capacity or the agent platform?"
6. "You still code. What does your own engineering week look like, and what do you look for in the engineers you hire?"
7. "What's the most important problem you'd want me to solve in my first six months?"

---

## 9. Landmines

- Don't repeat private numbers Abhay shared (revenue, deal sizes, runway) as if you'd researched them.
- Don't name the employer's internal products or customers, or criticise the employer.
- Don't claim a Series B; only the $20.8M Series A (Dec 2024, led by Canaan) is public.
- Don't invent any **[fill]** detail live. "I'd have to check the exact number" is fine.
- Don't overclaim the take-home: "the same decision, at much smaller scale".
- Don't bring up compensation.
