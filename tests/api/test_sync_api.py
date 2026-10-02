from dataclasses import replace
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from helpers import (
    KEY_A,
    KEY_B,
    add_pull_source,
    app_state,
    discourse_http,
    memory_adapters,
    seed_source,
)
from sqlalchemy import exc as sa_exc

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.enums import SourceMode, SourceType
from feedback_ingest.domain.errors import TransientError
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


def test_409_unless_an_enabled_pull_source(
    app_client: TestClient, adapters: Adapters, forum: Source
) -> None:
    push_mode = forum.model_copy(
        update={"id": "src-forum-push", "mode": SourceMode.PUSH, "webhook_secret": "s"}
    )
    adapters.sources.add(push_mode)
    adapters.sources.set_enabled(forum.id, forum.tenant_id, False)
    for source_id in (f"src-{forum.tenant_id}-{SourceType.PLAYSTORE}", push_mode.id, forum.id):
        result = _sync(app_client, source_id)
        assert result == {
            "status": 409,
            "detail": f"source {source_id} is not an enabled pull source",
        }
    assert sum(app_state(app_client).adapters.queue.counts().values()) == 0


def test_502_with_the_pull_result_when_the_source_fails(
    app_client: TestClient, forum: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(url: str, _params: dict[str, str]) -> dict[str, object]:
        msg = f"503 from {url}"
        raise TransientError(msg)

    monkeypatch.setattr(app_state(app_client).pull.http, "get_json", down)
    result = _sync(app_client, forum.id)
    assert (result["status"], result["pages"]) == (502, 0)
    assert result["error"] == "503 from https://forum.example.test/search.json"


def test_503_when_storage_is_down(
    app_client: TestClient, forum: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = sa_exc.OperationalError("INSERT", {}, Exception("disk I/O error"))

    def down(*_args: object) -> str:
        raise error

    monkeypatch.setattr(app_state(app_client).adapters.queue, "enqueue", down)
    assert _sync(app_client, forum.id) == {"status": 503, "detail": "storage unavailable"}
