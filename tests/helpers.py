import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from feedback_ingest.adapters.http.httpx_client import HttpxClient
from feedback_ingest.adapters.memory import stores
from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.adapters.memory.queue import MemoryRawEventQueue
from feedback_ingest.api.deps import Adapters, AppState
from feedback_ingest.config import Settings
from feedback_ingest.domain.enums import SourceMode, SourceType
from feedback_ingest.domain.models import Source, Tenant
from feedback_ingest.main import create_app
from feedback_ingest.utils.hashing import sha256_text
from feedback_ingest.utils.signing import sign

FIXTURES = Path(__file__).parent / "fixtures"
FORUM = "https://forum.example.test"
SECRET = "whsec-test-0123456789"  # noqa: S105  synthetic test secret
TOKEN = "bootstrap-test"  # noqa: S105  synthetic test token
KEY_A, KEY_B = "key-tenant-a", "key-tenant-b"
MINE, THEIRS = {"X-API-Key": KEY_A}, {"X-API-Key": KEY_B}
POLL_SECONDS = 0.05


def fixture_body(source_type: SourceType, name: str) -> bytes:
    return (FIXTURES / source_type / f"{name}.json").read_bytes()


def load(source_type: SourceType, name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(fixture_body(source_type, name))
    return payload


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


def add_pull_source(
    adapters: Adapters, source_id: str, cursor: str | None = None, base_url: str = FORUM
) -> Source:
    source = Source(
        id=source_id,
        tenant_id="tenant-a",
        type=SourceType.DISCOURSE,
        name="tenant-a forum",
        mode=SourceMode.PULL,
        config={"base_url": base_url, "start_after": "2026-02-01"},
        cursor=cursor,
    )
    adapters.sources.add(source)
    return source


def push(client: TestClient, source_id: str, body: bytes, secret: str = SECRET) -> httpx2.Response:
    headers = {"X-Signature": sign(secret, body)}
    return client.post(f"/v1/sources/{source_id}/events", content=body, headers=headers)


def client_for(adapters: Adapters, **settings: object) -> TestClient:
    defaults = {"worker_enabled": False, "scheduler_enabled": False}
    return TestClient(create_app(Settings.model_validate(defaults | settings), adapters=adapters))


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
