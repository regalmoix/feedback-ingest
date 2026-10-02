from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import KEY_A, KEY_B, POLL_SECONDS, client_for, memory_adapters, seed_source
from sqlalchemy import Engine

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.adapters.sqlalchemy.db import make_engine
from feedback_ingest.adapters.sqlalchemy.tables import Base
from feedback_ingest.api.deps import Adapters
from feedback_ingest.config import Settings
from feedback_ingest.domain.models import Source


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 1, 1, 12, 0))


@pytest.fixture
def adapters(clock: FixedClock) -> Adapters:
    return memory_adapters(clock)


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
    )
