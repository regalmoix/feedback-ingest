import time
from collections.abc import Callable
from pathlib import Path

import pytest

from feedback_ingest.config import Settings

POLL_SECONDS = 0.05


def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            pytest.fail(f"condition not met within {timeout}s")
        time.sleep(POLL_SECONDS)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'e2e.db'}", worker_poll_seconds=POLL_SECONDS
    )
