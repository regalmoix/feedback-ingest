import threading
from collections.abc import Iterator
from datetime import datetime

import pytest
from api.conftest import memory_adapters
from e2e.conftest import add_pull_source, discourse_http, wait_until

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.api.deps import Adapters
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.services.pull import PullResult, PullService
from feedback_ingest.services.scheduler import SchedulerService


@pytest.fixture
def adapters() -> Adapters:
    a = memory_adapters(FixedClock(datetime(2026, 3, 1, 12, 0)))
    add_pull_source(a, "src-forum")
    return a


@pytest.fixture
def scheduler(adapters: Adapters) -> Iterator[SchedulerService]:
    ingestion = IngestionService(adapters.queue, adapters.clock)
    pull = PullService(adapters.sources, ingestion, discourse_http(), adapters.clock)
    scheduler = SchedulerService(pull, interval_seconds=0.01)
    yield scheduler
    scheduler.stop()


def test_run_once_syncs_every_pull_source(scheduler: SchedulerService) -> None:
    [result] = scheduler.run_once()
    assert (result.source_id, result.accepted, result.error) == ("src-forum", 4, None)


def test_start_and_stop_the_thread(adapters: Adapters, scheduler: SchedulerService) -> None:
    scheduler.start()
    assert scheduler.alive
    wait_until(lambda: sum(adapters.queue.counts().values()) == 4)
    scheduler.stop()
    assert not scheduler.alive


def test_a_failing_tick_does_not_stop_the_next(
    scheduler: SchedulerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks: list[int] = []

    def crash() -> list[PullResult]:
        ticks.append(1)
        msg = "storage unavailable"
        raise RuntimeError(msg)

    monkeypatch.setattr(scheduler.pull, "sync_all", crash)
    scheduler.start()
    wait_until(lambda: len(ticks) >= 2)
    assert scheduler.alive


def test_stop_warns_when_a_sync_outlives_the_join(
    scheduler: SchedulerService, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    started, release = threading.Event(), threading.Event()

    def slow() -> list[PullResult]:
        started.set()
        release.wait(5)
        return []

    monkeypatch.setattr(scheduler.pull, "sync_all", slow)
    monkeypatch.setattr("feedback_ingest.services.scheduler._JOIN_SECONDS", 0.01)
    scheduler.start()
    assert started.wait(5)
    scheduler.stop()
    release.set()
    assert "scheduler still syncing on stop" in caplog.text
