import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from discourse_mock import discourse_http
from fastapi.testclient import TestClient
from helpers import KEY_A, KEY_B, POLL_SECONDS, TOKEN, client_for, memory_adapters, seed_source
from sqlalchemy import Engine

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.adapters.sqlalchemy.db import make_engine
from feedback_ingest.adapters.sqlalchemy.tables import Base
from feedback_ingest.api.deps import Adapters
from feedback_ingest.config import Settings
from feedback_ingest.domain.models import Source


@pytest.fixture(autouse=True)
def _no_fi_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings read FI_* from the environment; a developer's shell must not change test results."""
    for name in [n for n in os.environ if n.startswith("FI_")]:
        monkeypatch.delenv(name)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 3, 1, 12, 0))


@pytest.fixture
def adapters(clock: FixedClock) -> Adapters:
    return replace(memory_adapters(clock), http=discourse_http())


@pytest.fixture
def app_client(adapters: Adapters) -> Iterator[TestClient]:
    with client_for(adapters) as client:
        yield client


@pytest.fixture
def source_a(adapters: Adapters) -> Source:
    return seed_source(adapters, "tenant-a", KEY_A)


@pytest.fixture
def source_b(adapters: Adapters) -> Source:
    return seed_source(adapters, "tenant-b", KEY_B)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """SQLite file and a running worker; the scheduler stays off unless a test turns it on."""
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'e2e.db'}",
        worker_poll_seconds=POLL_SECONDS,
        scheduler_enabled=False,
        bootstrap_token=TOKEN,
    )
