from dataclasses import replace
from datetime import datetime

import pytest
from e2e.conftest import add_pull_source, discourse_http
from fastapi.testclient import TestClient

from api.conftest import KEY_A, KEY_B, app_state, memory_adapters, seed_source
from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.models import Source


@pytest.fixture
def adapters() -> Adapters:
    a = memory_adapters(FixedClock(datetime(2026, 3, 1, 12, 0)))
    return replace(a, http=discourse_http())


@pytest.fixture
def forum(adapters: Adapters) -> Source:
    seed_source(adapters, "tenant-a", KEY_A)
    return add_pull_source(adapters, "src-forum")


def _sync(client: TestClient, source_id: str, api_key: str | None = KEY_A) -> dict[str, object]:
    headers = {"X-API-Key": api_key} if api_key else {}
    response = client.post(f"/v1/sources/{source_id}/sync", headers=headers)
    body: dict[str, object] = response.json()
    return {"status": response.status_code, **body}


def test_401_without_an_api_key(app_client: TestClient, forum: Source) -> None:
    assert _sync(app_client, forum.id, api_key=None)["status"] == 401


@pytest.mark.usefixtures("source_b")
def test_404_for_another_tenants_source(app_client: TestClient, forum: Source) -> None:
    assert _sync(app_client, forum.id, api_key=KEY_B)["status"] == 404
    assert _sync(app_client, "src-unknown")["status"] == 404


def test_200_with_the_pull_result(app_client: TestClient, forum: Source) -> None:
    assert _sync(app_client, forum.id) == {
        "status": 200,
        "source_id": "src-forum",
        "pages": 2,
        "accepted": 4,
        "duplicates": 0,
        "cursor": "2026-02-08T00:00:00",
        "error": None,
    }
    assert sum(app_state(app_client).adapters.queue.counts().values()) == 4


def test_404_for_a_push_only_source(app_client: TestClient, forum: Source) -> None:
    push_only = f"src-{forum.tenant_id}-playstore"
    result = _sync(app_client, push_only)
    assert result["status"] == 404
    assert "push-only" in str(result["detail"])


def test_health_reports_the_scheduler(app_client: TestClient) -> None:
    assert app_client.get("/health").json()["scheduler_alive"] is True
