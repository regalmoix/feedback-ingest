from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.adapters.sqlalchemy.db import make_engine
from feedback_ingest.adapters.sqlalchemy.tables import Base

T0 = datetime(2026, 1, 1, 12, 0)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(T0)
