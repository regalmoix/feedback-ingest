import logging
from datetime import datetime

import httpx
import pytest
from api.conftest import KEY_A, memory_adapters, seed_source
from e2e.conftest import add_pull_source, discourse_http

from feedback_ingest.adapters.http.httpx_client import HttpxClient
from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.enums import EventStatus, SourceMode
from feedback_ingest.domain.models import RawEvent
from feedback_ingest.ports.http import HttpClient
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.services.pull import PullService

NOW = datetime(2026, 3, 1, 12, 0)
CURSOR = "2026-02-01T06:00:00"


@pytest.fixture
def adapters() -> Adapters:
    a = memory_adapters(FixedClock(NOW))
    seed_source(a, "tenant-a", KEY_A)
    return a


def _service(adapters: Adapters, http: HttpClient | None = None) -> PullService:
    ingestion = IngestionService(adapters.queue, adapters.clock)
    return PullService(adapters.sources, ingestion, http or discourse_http(), adapters.clock)


def _stored_cursor(adapters: Adapters, source_id: str) -> str | None:
    source = adapters.sources.get(source_id, tenant_id="tenant-a")
    assert source is not None
    return source.cursor


def test_transient_error_on_page_two_keeps_page_one(
    adapters: Adapters, caplog: pytest.LogCaptureFixture
) -> None:
    source = add_pull_source(adapters, "src-forum", cursor=CURSOR)
    result = _service(adapters, discourse_http(fail_page="2")).sync(source)
    assert (result.pages, result.accepted, result.cursor) == (1, 3, CURSOR)
    assert result.error is not None
    assert result.error.startswith("TransientError: 503")
    assert _stored_cursor(adapters, "src-forum") == CURSOR
    assert adapters.queue.counts()[EventStatus.PENDING] == 3
    assert next(r.levelno for r in caplog.records if r.name.endswith("pull")) == logging.WARNING


def test_the_cursor_is_saved_only_after_the_whole_page_is_accepted(
    adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = add_pull_source(adapters, "src-forum", cursor=CURSOR)
    enqueue, calls = adapters.queue.enqueue, []

    def fails_on_the_final_pages_payload(event: RawEvent) -> bool:
        calls.append(event.id)
        if len(calls) == 4:  # page 1 holds 3 payloads, the final page 1
            msg = "disk full"
            raise RuntimeError(msg)
        return enqueue(event)

    monkeypatch.setattr(adapters.queue, "enqueue", fails_on_the_final_pages_payload)
    result = _service(adapters).sync(source)
    assert (result.pages, result.error) == (1, "RuntimeError (see logs)")
    assert _stored_cursor(adapters, "src-forum") == CURSOR


def test_a_window_past_the_page_cap_is_an_error_and_keeps_the_cursor(adapters: Adapters) -> None:
    endless = {"posts": [], "grouped_search_result": {"more_full_page_results": True}}
    http = HttpxClient(httpx.MockTransport(lambda _: httpx.Response(200, json=endless)))
    source = add_pull_source(adapters, "src-forum", cursor=CURSOR)
    result = _service(adapters, http).sync(source)
    assert (result.pages, result.error) == (20, "TransformError (see logs)")
    assert _stored_cursor(adapters, "src-forum") == CURSOR


def test_sync_all_continues_past_a_broken_source(
    adapters: Adapters, caplog: pytest.LogCaptureFixture
) -> None:
    add_pull_source(adapters, "src-a-broken", cursor="yesterday")
    add_pull_source(adapters, "src-b-forum")
    push_only = adapters.sources.list_by_mode(SourceMode.PUSH)[0]
    adapters.sources.add(push_only.model_copy(update={"id": "src-c", "mode": SourceMode.PULL}))
    results = _service(adapters).sync_all()
    assert [r.source_id for r in results] == ["src-a-broken", "src-b-forum", "src-c"]
    assert results[0].error == "TransformError (see logs)"
    assert (results[1].accepted, results[1].error) == (4, None)
    assert results[2].error is not None
    assert results[2].error.startswith("ConfigError: playstore sources are push-only")
    assert any(r.levelno == logging.ERROR for r in caplog.records)
