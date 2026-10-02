from collections.abc import Iterator
from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from feedback_ingest.adapters.http.httpx_client import HttpxClient
from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.adapters.memory.queue import MemoryRawEventQueue
from feedback_ingest.adapters.memory.stores import (
    MemoryFeedbackStore,
    MemorySourceStore,
    MemoryTenantStore,
)
from feedback_ingest.api.deps import Adapters, AppState
from feedback_ingest.config import Settings
from feedback_ingest.domain.enums import SourceMode, SourceType
from feedback_ingest.domain.models import Source, Tenant
from feedback_ingest.main import create_app
from feedback_ingest.utils.hashing import sha256_text
from feedback_ingest.utils.signing import sign

FIXTURES = Path(__file__).parents[1] / "fixtures"
SECRET = "whsec-test"  # noqa: S105  synthetic test secret
KEY_A, KEY_B = "key-tenant-a", "key-tenant-b"
MINE, THEIRS = {"X-API-Key": KEY_A}, {"X-API-Key": KEY_B}


def fixture_body(source_type: SourceType, name: str) -> bytes:
    return (FIXTURES / source_type / f"{name}.json").read_bytes()


def memory_adapters(clock: FixedClock) -> Adapters:
    return Adapters(
        tenants=MemoryTenantStore(),
        sources=MemorySourceStore(),
        feedback=MemoryFeedbackStore(),
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
        config={"base_url": "https://forum.example.test"},
        webhook_secret=SECRET,
        cursor=None,
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


@pytest.fixture
def adapters(clock: FixedClock) -> Adapters:
    return memory_adapters(clock)


@pytest.fixture
def app_client(adapters: Adapters) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(worker_enabled=False), adapters=adapters)) as client:
        yield client


@pytest.fixture
def source_a(adapters: Adapters) -> Source:
    return seed_source(adapters, "tenant-a", KEY_A)


@pytest.fixture
def source_b(adapters: Adapters) -> Source:
    return seed_source(adapters, "tenant-b", KEY_B)
