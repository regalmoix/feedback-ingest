import threading
from collections.abc import Iterator
from datetime import datetime

import pytest
from helpers import add_pull_source, discourse_http, memory_adapters, wait_until

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.enums import SourceMode
from feedback_ingest.domain.models import Source
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


def test_start_and_stop_the_thread(adapters: Adapters, scheduler: SchedulerService) -> None:
    scheduler.start()
    assert scheduler.alive
    wait_until(lambda: sum(adapters.queue.counts().values()) == 4)
    scheduler.stop()
    assert not scheduler.alive


def test_a_failing_tick_does_not_stop_the_next_and_shows_in_health(
    scheduler: SchedulerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks: list[int] = []

    def crash(_: SourceMode) -> list[Source]:
        ticks.append(1)
        msg = "storage unavailable"
        raise RuntimeError(msg)

    monkeypatch.setattr(scheduler.pull.sources, "list_by_mode", crash)
    scheduler.start()
    wait_until(lambda: len(ticks) >= 2)
    assert scheduler.alive
    assert scheduler.last_errors == {"<tick>": "RuntimeError"}


def test_a_crashing_source_does_not_stop_the_next(
    adapters: Adapters,
    scheduler: SchedulerService,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    add_pull_source(adapters, "src-a-broken")  # listed before src-forum
    sync = scheduler.pull.sync

    def broken_first(source: Source) -> PullResult:
        if source.id == "src-a-broken":
            msg = "bug in our code"
            raise RuntimeError(msg)
        return sync(source)

    monkeypatch.setattr(scheduler.pull, "sync", broken_first)
    scheduler.start()
    wait_until(lambda: sum(adapters.queue.counts().values()) == 4)
    wait_until(lambda: scheduler.last_errors == {"src-a-broken": "internal error (see logs)"})
    failed = next(r for r in caplog.records if r.message == "scheduled sync failed")
    assert vars(failed)["tenant_id"] == "tenant-a"
    assert vars(failed)["source_id"] == "src-a-broken"


def test_stop_warns_when_a_sync_outlives_the_join(
    scheduler: SchedulerService, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    started, release = threading.Event(), threading.Event()

    def slow(source: Source) -> PullResult:
        started.set()
        release.wait(5)
        return PullResult(source_id=source.id)

    monkeypatch.setattr(scheduler.pull, "sync", slow)
    monkeypatch.setattr("feedback_ingest.services.scheduler._JOIN_SECONDS", 0.01)
    scheduler.start()
    assert started.wait(5)
    scheduler.stop()
    release.set()
    assert "scheduler still syncing on stop" in caplog.text


def test_a_tick_records_which_sources_failed(
    scheduler: SchedulerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    errors: list[str | None] = ["503 from x"]
    monkeypatch.setattr(
        scheduler.pull, "sync", lambda s: PullResult(source_id=s.id, error=errors[0])
    )
    scheduler.start()
    wait_until(lambda: scheduler.last_errors == {"src-forum": "503 from x"})
    errors[0] = None
    wait_until(lambda: scheduler.last_errors == {})
