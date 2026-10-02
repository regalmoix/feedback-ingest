import logging
from urllib.parse import urlencode

import pytest
from discourse_stub import (
    BASE,
    CLOCK,
    DEADLINE,
    PULLER,
    Route,
    StubHttp,
    post,
    pull_source,
    routes,
)

from feedback_ingest.domain.errors import TransformError, TransientError

SEARCH_1 = (f"{BASE}/search.json", "1")


def _posts_route(topic_id: int, ids: list[int]) -> tuple[str, str]:
    return f"{BASE}/t/{topic_id}/posts.json?{urlencode([('post_ids[]', i) for i in ids])}", ""


def test_transient_error_on_page_two_keeps_page_one() -> None:
    found = routes([list(range(1, 51)), [51]])
    found[f"{BASE}/search.json", "2"] = TransientError("503 from search.json")
    pages = PULLER.pull(pull_source(cursor="2026-02-01T00:30:00"), StubHttp(found), CLOCK, DEADLINE)
    first = next(pages)
    assert len(first.payloads) == 50
    assert first.cursor == "2026-02-01T00:30:00"
    with pytest.raises(TransientError):
        next(pages)


def test_a_post_omitted_by_posts_json_stops_the_pull() -> None:
    found = routes([[1, 3]])
    found[_posts_route(10, [1, 3])] = {"post_stream": {"posts": [post(1)]}}
    with pytest.raises(TransientError, match=r"topic 10 omitted posts \[3\]"):
        list(PULLER.pull(pull_source(), StubHttp(found), CLOCK, DEADLINE))


@pytest.mark.parametrize(
    ("route", "body"),
    [
        (SEARCH_1, {"unexpected": True}),
        (SEARCH_1, {"posts": []}),  # no grouped_search_result: not proof of a last page
        (_posts_route(10, [1]), {"unexpected": True}),
    ],
)
def test_unexpected_response_shape_is_transient(route: tuple[str, str], body: Route) -> None:
    found = routes([[1]]) | {route: body}
    with pytest.raises(TransientError, match="unexpected response shape"):
        list(PULLER.pull(pull_source(), StubHttp(found), CLOCK, DEADLINE))


def test_search_error_text_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    found = routes([[1]]) | {SEARCH_1: {"posts": [], "grouped_search_result": {"error": "boom"}}}
    with pytest.raises(TransformError) as raised:
        list(PULLER.pull(pull_source(), StubHttp(found), CLOCK, DEADLINE))
    assert str(raised.value) == "discourse search reported an error"
    [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "boom" in warning.getMessage()
    assert (vars(warning)["tenant_id"], vars(warning)["source_id"]) == (
        "tenant-test",
        "src-discourse",
    )
