from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import pytest
from connector_fixtures import source

from feedback_ingest.connectors.discourse import DiscourseConnector
from feedback_ingest.domain.enums import SourceMode, SourceType
from feedback_ingest.domain.errors import TransientError

BASE = "https://forum.example.test"
NOW = datetime(2026, 3, 1, 12, 0)  # noqa: DTZ001  naive UTC is the storage convention
START = datetime(2026, 2, 1)  # noqa: DTZ001  naive UTC is the storage convention
TITLES = {10: '<span class="search-highlight">Dark</span> mode', 20: "Login loop"}
Route = dict[str, Any] | Exception


class StubHttp:
    def __init__(self, routes: dict[tuple[str, str], Route]) -> None:
        self.routes = routes
        self.queries: list[str] = []

    def get_json(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        self.queries.append(params.get("q", ""))
        found = self.routes[url, params.get("page", "")]
        if isinstance(found, Exception):
            raise found
        return found


def _created(post_id: int) -> datetime:
    return START + (timedelta(minutes=post_id) if post_id <= 50 else timedelta(days=1))


def _topic(post_id: int) -> int:
    return 10 if post_id % 2 else 20


def _post(post_id: int) -> dict[str, Any]:
    return {
        "id": post_id,
        "topic_id": _topic(post_id),
        "post_number": post_id,
        "username": f"user_{post_id}",
        "created_at": _created(post_id).isoformat(),
        "cooked": f"<p>post {post_id}</p>",
        "topic_slug": f"topic-{_topic(post_id)}",
    }


def _routes(page_ids: list[list[int]]) -> dict[tuple[str, str], Route]:
    routes: dict[tuple[str, str], Route] = {}
    for page, ids in enumerate(page_ids, start=1):
        hits = [
            {"id": i, "topic_id": _topic(i), "created_at": _created(i).isoformat()}
            | {"topic_title_headline": TITLES[_topic(i)]}
            for i in ids
        ]
        routes[f"{BASE}/search.json", str(page)] = {"posts": hits}
        for topic_id in (10, 20):
            topic_ids = [i for i in ids if _topic(i) == topic_id]
            query = urlencode([("post_ids[]", i) for i in topic_ids])
            posts = [_post(i) for i in topic_ids]
            routes[f"{BASE}/t/{topic_id}/posts.json?{query}", ""] = {
                "post_stream": {"posts": posts}
            }
    return routes


def test_pages_carry_titles_and_the_cursor_moves_on_the_final_page() -> None:
    http = StubHttp(_routes([list(range(1, 51)), [51]]))
    puller = DiscourseConnector()
    src = source(SourceType.DISCOURSE, SourceMode.PULL)
    first, last = puller.pull(src, http, NOW)
    assert len(first.payloads) == 50
    assert {p["topic_title"] for p in first.payloads} == {"Dark mode", "Login loop"}
    assert first.cursor == "2026-02-01"
    assert last.cursor == "2026-02-01T23:59:00"
    assert http.queries[0] == "after:2026-02-01 before:2026-03-02"
    records = [r for p in first.payloads for r in puller.transform(src, p)]
    assert sorted(int(r.external_id) for r in records) == list(range(1, 51))
    assert {r.title for r in records} == {"Dark mode", "Login loop"}


def test_transient_error_on_page_two_keeps_page_one() -> None:
    routes = _routes([list(range(1, 51))])
    routes[f"{BASE}/search.json", "2"] = TransientError("503 from search.json")
    src = source(SourceType.DISCOURSE, SourceMode.PULL)
    resumed = src.model_copy(update={"cursor": "2026-02-01T00:30:00"})
    pages = DiscourseConnector().pull(resumed, StubHttp(routes), NOW)
    first = next(pages)
    assert len(first.payloads) == 50
    assert first.cursor == "2026-02-01T00:30:00"
    with pytest.raises(TransientError):
        next(pages)
