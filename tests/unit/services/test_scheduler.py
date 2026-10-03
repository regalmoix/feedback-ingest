import threading
from collections.abc import Iterator

import pytest
from helpers import add_pull_source, wait_until
from test_pull import service

from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.enums import SourceMode
from feedback_ingest.domain.models import Source
from feedback_ingest.services.pull import PullResult
from feedback_ingest.services.scheduler import SchedulerService


@pytest.fixture
def scheduler(adapters: Adapters) -> Iterator[SchedulerService]:
    add_pull_source(adapters, "src-forum")
    scheduler = SchedulerService(service(adapters), interval_seconds=0.01)
    yield scheduler
    scheduler.stop()


def test_start_and_stop_the_thread(adapters: Adapters, scheduler: SchedulerService) -> None:
    scheduler.start()
    assert scheduler.alive
    wait_until(lambda: sum(adapters.queue.counts().values()) == 4)
    scheduler.stop()
    assert not scheduler.alive


def test_a_failing_tick_does_not_stop_the_next_and_shows_in_health(
    adapters: Adapters, scheduler: SchedulerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_pull_source(adapters, "src-second")
    list_enabled, ticks = scheduler.pull.sources.list_enabled, []

    def crash_after_first(mode: SourceMode) -> list[Source]:
        ticks.append(1)
        if len(ticks) == 1:
            return list_enabled(mode)
        msg = "storage unavailable"
        raise RuntimeError(msg)

    monkeypatch.setattr(scheduler.pull.sources, "list_enabled", crash_after_first)
    scheduler.start()
    wait_until(lambda: len(ticks) >= 3)
    assert scheduler.alive
    assert scheduler.failing_sources == 2  # every enabled pull source counts on a broken tick


def test_a_tick_that_fails_before_listing_any_source_still_counts(
    scheduler: SchedulerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scheduler.pull.sources, "list_enabled", lambda _: 1 / 0)
    scheduler.start()
    wait_until(lambda: scheduler.failing_sources == 1)


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
    wait_until(lambda: scheduler.failing_sources == 1)
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


def test_a_tick_counts_the_sources_that_failed(
    scheduler: SchedulerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    errors: list[str | None] = ["503 from x"]
    monkeypatch.setattr(
        scheduler.pull, "sync", lambda s: PullResult(source_id=s.id, error=errors[0])
    )
    scheduler.start()
    wait_until(lambda: scheduler.failing_sources == 1)
    errors[0] = None
    wait_until(lambda: scheduler.failing_sources == 0)
