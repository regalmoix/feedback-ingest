import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from feedback_ingest.adapters.http.httpx_client import HttpxClient
from feedback_ingest.adapters.memory import stores
from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.adapters.memory.queue import MemoryRawEventQueue
from feedback_ingest.api.deps import Adapters, AppState
from feedback_ingest.domain.enums import SourceMode, SourceType
from feedback_ingest.domain.models import Source, Tenant
from feedback_ingest.utils.hashing import sha256_text
from feedback_ingest.utils.signing import sign

FIXTURES = Path(__file__).parent / "fixtures"
PULL_FIXTURES = FIXTURES / "discourse" / "pull"
FORUM = "https://forum.example.test"
SECRET = "whsec-test"  # noqa: S105  synthetic test secret
KEY_A, KEY_B = "key-tenant-a", "key-tenant-b"
MINE, THEIRS = {"X-API-Key": KEY_A}, {"X-API-Key": KEY_B}
POLL_SECONDS = 0.05


def fixture_body(source_type: SourceType, name: str) -> bytes:
    return (FIXTURES / source_type / f"{name}.json").read_bytes()


def memory_adapters(clock: FixedClock) -> Adapters:
    return Adapters(
        tenants=stores.MemoryTenantStore(),
        sources=stores.MemorySourceStore(),
        feedback=stores.MemoryFeedbackStore(),
        queue=MemoryRawEventQueue(),
        http=HttpxClient(),
        clock=clock,
    )


def seed_source(
    adapters: Adapters, tenant_id: str, api_key: str, source_type: SourceType = SourceType.PLAYSTORE
) -> Source:
    adapters.tenants.add(Tenant(id=tenant_id, name=tenant_id, api_key_hash=sha256_text(api_key)))
    source = Source(
        id=f"src-{tenant_id}-{source_type}",
        tenant_id=tenant_id,
        type=source_type,
        name=f"{tenant_id} {source_type}",
        mode=SourceMode.PUSH,
        config={"base_url": FORUM},
        webhook_secret=SECRET,
        cursor=None,
    )
    adapters.sources.add(source)
    return source


def add_pull_source(adapters: Adapters, source_id: str, cursor: str | None = None) -> Source:
    source = Source(
        id=source_id,
        tenant_id="tenant-a",
        type=SourceType.DISCOURSE,
        name="tenant-a forum",
        mode=SourceMode.PULL,
        config={"base_url": FORUM, "start_after": "2026-02-01"},
        cursor=cursor,
    )
    adapters.sources.add(source)
    return source


def push(
    client: TestClient, source_id: str, body: bytes, api_key: str, secret: str = SECRET
) -> httpx2.Response:
    headers = {"X-API-Key": api_key, "X-Signature": sign(secret, body)}
    return client.post(f"/v1/sources/{source_id}/events", content=body, headers=headers)


def app_state(client: TestClient) -> AppState:
    assert isinstance(client.app, FastAPI)
    ctx: AppState = client.app.state.ctx
    return ctx


def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            pytest.fail(f"condition not met within {timeout}s")
        time.sleep(POLL_SECONDS)


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((PULL_FIXTURES / f"{name}.json").read_text())
    return data


# Two search pages and their posts.json, whatever the date window asked for.
def discourse_http(fail_page: str | None = None) -> HttpxClient:
    def handle(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if request.url.path == "/search.json":
            if params["page"] == fail_page:
                return httpx.Response(503, text="slow down")
            return httpx.Response(200, json=_load(f"search_page{params['page']}"))
        topic_id = request.url.path.split("/")[2]
        wanted = {int(i) for i in params.get_list("post_ids[]")}
        posts = _load(f"posts_topic_{topic_id}")["post_stream"]["posts"]
        kept = [p for p in posts if p["id"] in wanted]
        return httpx.Response(200, json={"post_stream": {"posts": kept}})

    return HttpxClient(transport=httpx.MockTransport(handle))
