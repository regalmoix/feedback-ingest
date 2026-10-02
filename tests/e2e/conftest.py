import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from feedback_ingest.adapters.http.httpx_client import HttpxClient
from feedback_ingest.api.deps import Adapters
from feedback_ingest.config import Settings
from feedback_ingest.domain.enums import SourceMode, SourceType
from feedback_ingest.domain.models import Source

POLL_SECONDS = 0.05


def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            pytest.fail(f"condition not met within {timeout}s")
        time.sleep(POLL_SECONDS)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'e2e.db'}", worker_poll_seconds=POLL_SECONDS
    )


PULL_FIXTURES = Path(__file__).parents[1] / "fixtures" / "discourse" / "pull"
FORUM = "https://forum.example.test"


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((PULL_FIXTURES / f"{name}.json").read_text())
    return data


def discourse_http(fail_page: str | None = None) -> HttpxClient:
    """Two search pages and their posts.json, whatever the date window asked for."""

    def handle(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if request.url.path == "/search.json":
            if params["page"] == fail_page:
                return httpx.Response(503, text="slow down")
            return httpx.Response(200, json=_load(f"search_page{params['page']}"))
        topic_id = request.url.path.split("/")[2]
        wanted = {int(i) for i in params.get_list("post_ids[]")}
        posts = _load(f"posts_topic_{topic_id}")["post_stream"]["posts"]
        return httpx.Response(
            200, json={"post_stream": {"posts": [p for p in posts if p["id"] in wanted]}}
        )

    return HttpxClient(transport=httpx.MockTransport(handle))


def add_pull_source(
    adapters: Adapters, source_id: str, tenant_id: str = "tenant-a", cursor: str | None = None
) -> Source:
    source = Source(
        id=source_id,
        tenant_id=tenant_id,
        type=SourceType.DISCOURSE,
        name=f"{tenant_id} forum",
        mode=SourceMode.PULL,
        config={"base_url": FORUM, "start_after": "2026-02-01"},
        cursor=cursor,
    )
    adapters.sources.add(source)
    return source
