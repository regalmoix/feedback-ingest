from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import pytest
from discourse_stub import BASE, DEADLINE, NOW, PULLER, StubHttp, pull_source, routes

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.domain.errors import TransformError, TransientError


def test_a_passed_deadline_stops_before_the_first_search_page() -> None:
    http = StubHttp(routes([[1]]))
    with pytest.raises(TransientError, match="pull deadline exceeded"):
        next(PULLER.pull(pull_source(), http, FixedClock(NOW), NOW - timedelta(seconds=1)))
    assert http.calls == []


def test_the_deadline_is_checked_before_each_posts_call(monkeypatch: pytest.MonkeyPatch) -> None:
    clock, http = FixedClock(NOW), StubHttp(routes([[1, 2]]))
    get_json = http.get_json

    def slow(url: str, params: Sequence[tuple[str, str]] = ()) -> dict[str, Any]:
        clock.advance(61)
        return get_json(url, params)

    monkeypatch.setattr(http, "get_json", slow)
    with pytest.raises(TransientError, match="pull deadline exceeded"):
        next(PULLER.pull(pull_source(), http, clock, NOW + timedelta(seconds=60)))
    assert http.calls == [f"{BASE}/search.json after:2026-02-01 before:2026-03-02"]


def test_a_window_end_past_the_calendar_is_a_transform_error() -> None:
    late = pull_source(cursor="9999-12-30T00:00:00")
    with pytest.raises(TransformError):
        next(PULLER.pull(late, StubHttp({}), FixedClock(NOW), DEADLINE))
