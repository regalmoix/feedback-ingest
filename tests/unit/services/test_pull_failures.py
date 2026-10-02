import logging

import httpx
import pytest
import test_pull
from helpers import add_pull_source, discourse_http
from test_pull import service, stored_cursor

from feedback_ingest.adapters.http.httpx_client import HttpxClient
from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.enums import EventStatus
from feedback_ingest.domain.models import RawEvent

adapters = test_pull.adapters  # the same fixture, registered for this module
CURSOR = "2026-02-01T06:00:00"


def test_transient_error_on_page_two_keeps_page_one(
    adapters: Adapters, caplog: pytest.LogCaptureFixture
) -> None:
    source = add_pull_source(adapters, "src-forum", cursor=CURSOR)
    result = service(adapters, discourse_http(fail_page="2")).sync(source)
    assert (result.pages, result.accepted, result.cursor) == (1, 3, CURSOR)
    assert result.error == "503 from https://forum.example.test/search.json"
    assert stored_cursor(adapters, "src-forum") == CURSOR
    assert adapters.queue.counts()[EventStatus.PENDING] == 3
    assert next(r.levelno for r in caplog.records if r.name.endswith("pull")) == logging.WARNING


def test_a_storage_failure_propagates_and_the_cursor_waits_for_the_whole_page(
    adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = add_pull_source(adapters, "src-forum", cursor=CURSOR)
    enqueue, calls = adapters.queue.enqueue, []

    def fails_on_the_final_pages_payload(event: RawEvent) -> str:
        calls.append(event.id)
        if len(calls) == 4:  # page 1 holds 3 payloads, the final page 1
            msg = "disk full"
            raise RuntimeError(msg)
        return enqueue(event)

    monkeypatch.setattr(adapters.queue, "enqueue", fails_on_the_final_pages_payload)
    with pytest.raises(RuntimeError, match="disk full"):
        service(adapters).sync(source)
    assert stored_cursor(adapters, "src-forum") == CURSOR


def test_a_window_past_the_page_cap_is_an_error_and_keeps_the_cursor(adapters: Adapters) -> None:
    endless = {"posts": [], "grouped_search_result": {"more_full_page_results": True}}
    http = HttpxClient(httpx.MockTransport(lambda _: httpx.Response(200, json=endless)))
    source = add_pull_source(adapters, "src-forum", cursor=CURSOR)
    result = service(adapters, http).sync(source)
    assert result.pages == 10
    assert result.error is not None
    assert "window exceeds 10 pages" in result.error
    assert stored_cursor(adapters, "src-forum") == CURSOR
