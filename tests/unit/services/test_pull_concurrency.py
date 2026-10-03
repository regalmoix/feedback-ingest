import logging
import threading
import time
from collections.abc import Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import KEY_A, MINE, add_pull_source, app_state, seed_source, wait_until
from test_pull import service

from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.errors import ConflictError, TransientError
from feedback_ingest.domain.models import Source
from feedback_ingest.services.pull import PullResult
from feedback_ingest.services.scheduler import SchedulerService


def test_a_second_sync_of_a_running_source_is_refused_and_the_scheduler_skips_it(
    adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, pull = add_pull_source(adapters, "src-forum"), service(adapters)
    started, release = threading.Event(), threading.Event()
    get_json = adapters.http.get_json

    def slow(url: str, params: Sequence[tuple[str, str]] = ()) -> dict[str, Any]:
        started.set()
        release.wait(5)
        return get_json(url, params)

    monkeypatch.setattr(adapters.http, "get_json", slow)
    first = threading.Thread(target=pull.sync, args=(source,))
    first.start()
    assert started.wait(5)
    with pytest.raises(ConflictError, match="already syncing"):
        pull.sync(source)
    assert SchedulerService(pull, 60)._sync_one(source) is False  # noqa: SLF001
    release.set()
    first.join(5)
    assert pull.sync(source).error is None  # the lock is released after a run


def test_the_endpoint_answers_409_while_a_sync_runs(
    app_client: TestClient, adapters: Adapters
) -> None:
    seed_source(adapters, "tenant-a", KEY_A)
    add_pull_source(adapters, "src-forum")
    held = threading.Lock()
    held.acquire()
    app_state(app_client).pull._running["src-forum"] = held  # noqa: SLF001
    response = app_client.post("/v1/sources/src-forum/sync", headers=MINE)
    assert (response.status_code, response.json()["detail"]) == (
        409,
        "source src-forum is already syncing",
    )


def test_an_empty_error_message_still_counts_as_a_failed_source(
    adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(*_args: object) -> dict[str, Any]:
        raise TransientError

    add_pull_source(adapters, "src-forum")
    monkeypatch.setattr(adapters.http, "get_json", down)
    scheduler = SchedulerService(service(adapters), interval_seconds=0.01)
    scheduler.start()
    wait_until(lambda: scheduler.failing_sources == 1)
    scheduler.stop()


def test_a_sync_that_crashes_during_shutdown_is_logged_as_abandoned(
    adapters: Adapters, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def crash(_source: Source) -> PullResult:
        msg = "interpreter shutting down"
        raise RuntimeError(msg)

    scheduler = SchedulerService(service(adapters), interval_seconds=60)
    monkeypatch.setattr(scheduler.pull, "sync", crash)
    scheduler._stop.set()  # noqa: SLF001
    scheduler._sync_one(add_pull_source(adapters, "src-forum"))  # noqa: SLF001
    [record] = [r for r in caplog.records if r.name.endswith("scheduler")]
    assert (record.levelno, record.getMessage()) == (logging.INFO, "sync abandoned at shutdown")


def _counting(
    adapters: Adapters, monkeypatch: pytest.MonkeyPatch, interval: float
) -> tuple[SchedulerService, list[str]]:
    add_pull_source(adapters, "src-forum")
    scheduler, calls = SchedulerService(service(adapters), interval_seconds=interval), []

    def counting(source: Source) -> PullResult:
        calls.append(source.id)
        return PullResult(source_id=source.id)

    monkeypatch.setattr(scheduler.pull, "sync", counting)
    return scheduler, calls


def test_a_stopped_scheduler_starts_again(
    adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduler, calls = _counting(adapters, monkeypatch, 0.01)
    scheduler.start()
    scheduler.stop()
    calls.clear()
    scheduler.start()
    wait_until(lambda: len(calls) >= 1, timeout=2)
    scheduler.stop()


def test_the_scheduler_waits_one_interval_before_the_first_tick(
    adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduler, calls = _counting(adapters, monkeypatch, 60)
    scheduler.start()
    time.sleep(0.2)
    scheduler.stop()
    assert calls == []
