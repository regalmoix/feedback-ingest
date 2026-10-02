from collections.abc import Sequence
from datetime import datetime, timedelta
from itertools import batched
from typing import Any
from urllib.parse import urlencode

from connector_fixtures import source

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.connectors.discourse import DiscourseConnector
from feedback_ingest.domain.enums import SourceMode, SourceType
from feedback_ingest.domain.models import Source

PULLER = DiscourseConnector()
BASE = "https://forum.example.test"
NOW = datetime(2026, 3, 1, 12, 0)
CLOCK, DEADLINE = FixedClock(NOW), NOW + timedelta(minutes=1)
START = datetime(2026, 2, 1)
HEADLINES = {10: '<span class="search-highlight">Dark</span> mode', 20: "Login loop"}
TOPICS = [{"id": 10, "title": "Dark mode"}, {"id": 20, "title": "Login loop"}]
Route = dict[str, Any] | Exception


class StubHttp:
    def __init__(self, routes: dict[tuple[str, str], Route]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def get_json(self, url: str, params: Sequence[tuple[str, str]] = ()) -> dict[str, Any]:
        query = dict(params)
        if "page" in query:
            self.calls.append(f"{url} {query['q']}")
            found = self.routes[url, query["page"]]
        else:
            url = f"{url}?{urlencode(params)}"
            self.calls.append(url)
            found = self.routes[url, ""]
        if isinstance(found, Exception):
            raise found
        return found


def pull_source(window_days: int = 60, cursor: str | None = None) -> Source:
    src = source(SourceType.DISCOURSE, SourceMode.PULL)
    config = {**src.config, "window_days": str(window_days)}
    return src.model_copy(update={"config": config, "cursor": cursor})


def created(post_id: int) -> datetime:
    return START + (timedelta(minutes=post_id) if post_id <= 50 else timedelta(days=1))


def topic(post_id: int) -> int:
    return 10 if post_id % 2 else 20


def post(post_id: int) -> dict[str, Any]:
    return {
        "id": post_id,
        "topic_id": topic(post_id),
        "post_number": post_id,
        "username": f"user_{post_id}",
        "created_at": created(post_id).isoformat(),
        "cooked": f"<p>post {post_id}</p>",
        "topic_slug": f"topic-{topic(post_id)}",
    }


def routes(page_ids: list[list[int]], *, topics: bool = False) -> dict[tuple[str, str], Route]:
    found: dict[tuple[str, str], Route] = {}
    for page, ids in enumerate(page_ids, start=1):
        hits = [
            {"id": i, "topic_id": topic(i), "created_at": created(i).isoformat()}
            | ({} if topics else {"topic_title_headline": HEADLINES[topic(i)]})
            for i in ids
        ]
        more = page < len(page_ids)
        search = {"posts": hits, "grouped_search_result": {"more_full_page_results": more}}
        found[f"{BASE}/search.json", str(page)] = search | ({"topics": TOPICS} if topics else {})
        for topic_id in (10, 20):
            for chunk in batched([i for i in ids if topic(i) == topic_id], 20):
                query = urlencode([("post_ids[]", i) for i in chunk])
                stream = {"post_stream": {"posts": [post(i) for i in chunk]}}
                found[f"{BASE}/t/{topic_id}/posts.json?{query}", ""] = stream
    return found
