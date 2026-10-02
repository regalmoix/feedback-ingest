# CLAUDE.md

Multi-tenant feedback ingestion service (take-home). Follow [AGENT_WORKFLOW.md](AGENT_WORKFLOW.md) for how
agents plan, build, review and hand over; this file holds only what is specific to this repo.

## Read first
- [docs/00_architecture.md](docs/00_architecture.md): current reference (diagrams, module map, requirements-to-test map).
- [docs/decisions/](docs/decisions/): ADR-001 storage and queue, ADR-002 record and idempotency, ADR-003 connectors.
- [docs/phases/](docs/phases/): per-phase design docs with "Deviations recorded".
- [docs/interview/](docs/interview/): whiteboard script, Q&A bank, failure scenarios, runbook, debt ledger.

## Commands
```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest
uv run uvicorn feedback_ingest.main:app
scripts/demo.sh            # nine-step demo; needs the network for the Discourse step
uv run pytest -m live      # real meta.discourse.org pull, opt-in
```
All four gates must be green before any commit. Settings use the `FI_` prefix (see `feedback_ingest/config.py`).

## Repo rules
- Python 3.12, uv, FastAPI, SQLAlchemy 2 (SQLite by default, `FI_DATABASE_URL` swaps), Pydantic v2, mypy strict, ruff ALL.
- Layout: `domain/` (models), `ports/` (Protocols), `adapters/` (sqlalchemy, memory, http), `connectors/` (one per source + registry), `services/`, `api/`, `wiring.py`, `main.py`. Services import ports only.
- Every port has a SQLite adapter and a memory fake; both run the contract tests under `tests/adapters/`.
- Add a source: enum value, connector file with its input model, metadata model in the union, `KIND_BY_SOURCE` entry, registry entry, fixtures under `tests/fixtures/<type>/`; the contract test fails until all exist.
- Files ≤120 lines. Comments only for `# ponytail:` markers (ceiling + upgrade) and rare "why".
- Fixtures are synthetic; never commit real ids, keys or customer text. `.seed.json` and `*.db*` are ignored.
- Known deliberate gaps are listed in the README and `docs/interview/debt_ledger.md`; do not "fix" them without a decision.

## Skills
Vendored under `.claude/skills/` (`ponytail`, `ponytail-review`, `ponytail-audit`, `ponytail-debt`,
`karpathy-guidelines`, `llm-council`); see `.claude/skills/ATTRIBUTION.md`. Load `ponytail` and
`karpathy-guidelines` at the start of every implementation or fix task.
