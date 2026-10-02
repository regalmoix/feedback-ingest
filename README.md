# Feedback Ingestion Service

A multi-tenant backend that ingests customer feedback from heterogeneous sources (Intercom, Play Store,
Twitter, Discourse) via both push (signed webhooks) and pull (polling a source API), stores every raw
payload durably, and transforms it into one uniform, de-duplicated feedback record that still carries
source-specific metadata.

## Run

```sh
uv sync
uv run pytest
uv run uvicorn feedback_ingest.main:app --reload   # main.py arrives in a later phase
```

## Docs

- [docs/PLAN.md](docs/PLAN.md)
- [docs/00_architecture.md](docs/00_architecture.md)
