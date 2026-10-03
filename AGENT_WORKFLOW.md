# Agent workflow

How to run a build with AI agents so the result is small, correct, and defensible by someone who did not
write it. Repo-agnostic: copy this file as is and put repo-specific rules in `CLAUDE.md`.

## 1. Roles

| Role | Who | Does | Never does |
|---|---|---|---|
| Orchestrator | the strongest reasoning model available (one session) | reads the problem, writes the plan and the per-phase design docs, frames decisions, vets review findings, merges, commits | writes product code |
| Implementer | a capable, cheaper coding model, one agent per phase | builds exactly what one design doc says, runs the gates, reports deviations | redesigns, edits docs beyond its phase doc, commits without green gates |
| Reviewer | same model as the implementer, several agents in parallel | reads and probes; reports findings with file:line, failure scenario, minimal fix | edits project files |
| Fixer | implementer model | applies a vetted fix brief verbatim, adds a test per behaviour change | re-litigates the brief |
| Council | five advisor agents, optionally five reviewers and a chairman | pressure-tests one decision with real stakes | builds anything |

Keep the orchestrator's own token use for thinking: planning, design docs, deciding between conflicting
findings, final review. Everything mechanical goes to agents.

Model tiers, cheapest that can do the job:
- Research, web reading, summarising, bulk doc drafting from sources, fixture generation: the fast tier
  (for example Sonnet).
- Implementation, fixes, reviews, mutation testing, deck building: the capable tier (for example Opus).
- Plans, design docs, council framing and synthesis, vetting conflicting findings, final judgement: the
  premium tier (for example Fable), and nothing else. If a task could be a Sonnet task, it is.

## 2. Skills every agent loads first

Vendor the skills under `.claude/skills/` so they work without plugin setup, then every implementer and
fixer prompt starts with: "Load `ponytail` and `karpathy-guidelines` via the Skill tool and obey them."

- `ponytail` (full): laziest working solution, stdlib first, no speculative abstractions, shortest diff.
  Deliberate shortcuts carry a `# ponytail:` comment naming the ceiling and the upgrade path.
- `karpathy-guidelines`: state assumptions, surgical changes, verifiable success criteria, report
  deviations instead of silently choosing.
- `ponytail-review` (diff) and `ponytail-audit` (whole repo): over-engineering hunts for the review fleet.
- `ponytail-debt`: harvests every `# ponytail:` marker into a ledger of "what I would do next".
- `llm-council`: five-advisor pressure test for decisions (section 5).

If the skills are installed as plugins instead, the names are prefixed (for example
`ponytail:ponytail`, `andrej-karpathy-skills:karpathy-guidelines`, `anthropic-skills:llm-council`).

## 3. The loop

```
plan → [per phase: design doc → implement → review fleet → fix → gates → commit] → final fleet → fix → handover
```

1. **Plan once.** One plan file: context, decisions table (choice, why, why not the alternatives),
   architecture sketch, folder layout, phases, verification. Copy it into the repo (`docs/PLAN.md`).
2. **Design doc per phase** (`docs/phases/NN_name.md`, one or two pages, plain language): what this phase
   builds in one paragraph, a glossary of new terms, the exact files and signatures, the tests that define
   done, and "how to explain this phase" in two sentences. The implementer builds from this and nothing else.
3. **Implement** with one agent per phase. The prompt names the doc, the conventions, the gates, the
   file-size cap, and ends with "report every deviation with a one-line reason". Deviations are then written
   back into the phase doc under "Deviations recorded", so docs never drift from code.
4. **Review fleet** (section 6) on the phase diff. Reviewers only read.
5. **Vet, then fix.** The orchestrator merges all findings into one brief, decides conflicts, marks what is
   kept on purpose, and dispatches one fixer. Repeat review-then-fix until a round reports nothing material
   (cap three rounds; log leftovers in the phase doc).
6. **Gates** must be green before every commit: lint, format check, strict type check, tests. Add an
   end-to-end test from the first phase that has a runnable surface.
7. **Commit per phase** with a message that says what and why. Never commit with red gates.

## 4. Conventions that keep agents honest

- Strict typing at the boundaries (Pydantic or equivalent for every shape crossing a boundary); no `Any`
  outside raw inbound payloads.
- Services are classes built from ports (Protocols); adapters implement ports; one real adapter and one
  in-memory fake per store and queue port (HttpClient and Clock have test stubs only), both run through the same contract tests.
- Files under about 120 lines; split rather than grow. Public surface small; helpers private.
- Minimal comments: `# ponytail:` markers and rare "why" notes only.
- Synthetic fixtures only; never real names, ids, keys or customer text.
- Every behaviour change ships with a test that fails without it. Reviewers verify this by mutation
  (flip the line, run the test, restore).

## 5. Councils

Run `llm-council` on decisions with real trade-offs that the whole build depends on (storage shape, core
data model, the main extension point). Typically two or three per project. Fixed constraints from the owner
go into the framed question as non-negotiable; the council refines within them and records dissent. Each
verdict becomes an ADR in `docs/decisions/` with a plain "how to say it" section. The advisor round carries
most of the value; run the peer-review and chairman rounds only when the advisors disagree.

## 6. The review fleet

Launch in parallel, each read-only, each told what is REQUIRED by the design (so it is not flagged):

| Reviewer | Looks for | Output |
|---|---|---|
| code review | correctness, spec and ADR violations, cross-module inconsistency, dead code, misleading markers | ranked findings, file:line, minimal fix |
| silent-failure hunt | swallowed errors, 2xx before commit, errors that become "no data", missing correlation ids, leaks; probes with scratch scripts, never the project | same, with the reproducing scenario |
| type design | invalid states constructible through public types, inconsistent port signatures, response models exposing too much | same |
| test coverage | mutation testing in a scratch copy; survivors with the exact assertion to add; order dependence; whether the requirements map names tests that really assert the requirement | same |
| ponytail review / audit | over-building: one-caller wrappers, speculative flexibility, duplicated test setup, reinvented stdlib | one line per cut, net lines |
| security | tenant isolation, auth and signature handling, secret exposure, SSRF, resource exhaustion, injection, defaults | ranked, "exploitable today" vs "hardening" |
| docs accuracy | every claim in README, architecture, ADRs and interview material checked against the code | table: claim, actual, suggested wording |

Run the first five after every phase (or every two phases on a small project), all seven on the final
tree. Reviewers that find nothing must say "No findings" explicitly.

## 7. Fix briefs

A fix brief is the orchestrator's vetted list, not a paste of the reviews. For each item: what to change,
where, the test that proves it, and the decision when reviewers conflicted. Items kept on purpose are
listed with the reason and later land in the debt ledger. The fixer applies every item, reports a checklist
(done or skipped with reason), and never weakens tooling config to get green.

## 8. Parallel work

Use isolated git worktrees for phases that touch disjoint files, branched from a committed base. Give each
agent an explicit file-ownership list and tell it to append rather than restructure shared wiring files.
Merge back on the orchestrator's side; conflicts should be unions of one or two lines. Never run two agents
that edit the same files at once; reviewers can run alongside an implementer because they only read.

## 9. Zero-intervention mode

When the owner wants no questions until done: ambiguities become stated assumptions in the phase doc;
stop only for destructive actions, credentials, or a verification failure that repeats after a reasonable
attempt. End with a recap: goal, key decisions, changes, validation, remaining risk.

## 10. Handover for a non-author

Produce, and keep in sync with the code: an architecture doc with a requirements-to-test map and diagrams;
ADRs with plain-language "how to say it"; a whiteboard script; a question bank; a failure-scenario table;
a runbook with real commands; an alternatives sheet; an extensions sheet; a glossary; a debt ledger from the
`# ponytail:` markers; a demo script that is rehearsed and known to pass. The final docs-accuracy reviewer
checks every sentence against the code before handover.

## 11. Agent prompt skeleton

```
You are <role> for <phase> of a project at <path>. FIRST load `ponytail` and `karpathy-guidelines` via the
Skill tool and obey them. Read, in full, in this order: <design doc>, <ADRs>, <conventions section>, then
the existing code under <dirs> so you reuse what exists. Build exactly what the doc specifies: <list>.
Rules: gates <commands> green at the end, iterate until so; no config weakening; files ≤120 lines;
mark deliberate shortcuts with `# ponytail:`; do not commit / commit as "<message>"; do not edit docs
except <named lines>. If the spec is ambiguous pick the simplest reading and note it; if it is wrong, fix
minimally and report. Report (≤N lines): files and line counts, gate outputs, test count, every deviation
with a one-line reason.
```

For reviewers replace the build instructions with the lens from section 6, "Do not edit files", and
"Say 'No findings' explicitly if clean".

## 12. What this workflow does well, and where to economise

Worth every token: the review fleet with fix loops (it finds the bugs confident implementers ship),
mutation-tested coverage, per-phase design docs with recorded deviations, ponytail with the debt ledger.
Worth it with care: councils (advisor round is the value; cap at three per project), the strong-model
orchestrator (spend it on design and on arbitrating conflicting findings). Marginal on their own: the
karpathy rules once ponytail and "report deviations" are in place; a feedback loop beyond the gates and one
rehearsed demo.
