import json
from collections.abc import Iterator

import pytest
from helpers import KEY_A, fixture_body, memory_adapters, seed_source, wait_until

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.enums import EventStatus, SourceType
from feedback_ingest.domain.models import RawEvent
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.services.pipeline import PipelineService
from feedback_ingest.services.worker import WorkerService


@pytest.fixture
def adapters(clock: FixedClock) -> Adapters:
    a = memory_adapters(clock)
    source = seed_source(a, "tenant-a", KEY_A)
    review = json.loads(fixture_body(SourceType.PLAYSTORE, "review"))
    for n in range(3):
        payload = review | {"reviewId": f"review-{n}"}
        IngestionService(a.queue, a.clock).accept(source, payload)
    return a


@pytest.fixture
def worker(adapters: Adapters) -> Iterator[WorkerService]:
    a = adapters
    pipeline = PipelineService(a.sources, a.feedback, a.queue, a.clock, 5, 300)
    worker = WorkerService(a.queue, pipeline, a.clock, poll_seconds=0.01, lease_seconds=30, batch=2)
    yield worker
    worker.stop()


def test_run_once_processes_one_claimed_batch(adapters: Adapters, worker: WorkerService) -> None:
    assert [worker.run_once(), worker.run_once(), worker.run_once()] == [2, 1, 0]
    assert adapters.queue.counts()[EventStatus.PROCESSED] == 3


def test_start_and_stop_the_thread(adapters: Adapters, worker: WorkerService) -> None:
    worker.start()
    assert worker.alive
    wait_until(lambda: adapters.queue.counts()[EventStatus.PROCESSED] == 3)
    worker.stop()
    assert not worker.alive


def test_a_crashing_process_does_not_kill_the_loop(
    worker: WorkerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def crash(event: RawEvent) -> EventStatus:
        calls.append(event.id)
        msg = "boom"
        raise RuntimeError(msg)

    monkeypatch.setattr(worker.pipeline, "process", crash)
    worker.batch = 3  # one crash must not strand the rest of its batch
    worker.start()
    wait_until(lambda: len(calls) == 3)
    assert worker.alive


def test_a_batch_that_only_crashes_is_not_progress_and_start_is_repeatable(
    worker: WorkerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    def crash(_event: RawEvent) -> EventStatus:
        msg = "boom"
        raise RuntimeError(msg)

    monkeypatch.setattr(worker.pipeline, "process", crash)
    worker.run_once()
    assert worker._last_ok_at is None  # noqa: SLF001
    worker.start()
    worker.stop()
    worker.start()  # stop() set the event; start() clears it
    assert worker.alive
