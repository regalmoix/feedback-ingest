import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from api.conftest import KEY_A, KEY_B, fixture_body, push
from feedback_ingest.api.deps import Adapters
from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.enums import EventStatus, SourceType
from feedback_ingest.domain.models import Source

BODY = fixture_body(SourceType.PLAYSTORE, "review")


@pytest.mark.parametrize("api_key", ["", "not-a-key"])
def test_missing_or_unknown_api_key_is_401(
    app_client: TestClient, source_a: Source, api_key: str
) -> None:
    response = push(app_client, source_a.id, BODY, api_key)
    assert response.status_code == 401
    assert app_client.post(f"/v1/sources/{source_a.id}/events", content=BODY).status_code == 401


@pytest.mark.usefixtures("source_b")
def test_another_tenants_source_is_404(app_client: TestClient, source_a: Source) -> None:
    assert push(app_client, source_a.id, BODY, KEY_B).status_code == 404


def test_bad_signature_is_401_and_nothing_is_stored(
    app_client: TestClient, adapters: Adapters, source_a: Source
) -> None:
    response = push(app_client, source_a.id, BODY, KEY_A, "wrong")
    assert response.status_code == 401
    assert adapters.queue.counts()[EventStatus.PENDING] == 0


@pytest.mark.parametrize("body", [b"[1, 2]", b'"text"', b"{not json", b"\xff"])
def test_body_that_is_not_a_json_object_is_400(
    app_client: TestClient, source_a: Source, body: bytes
) -> None:
    assert push(app_client, source_a.id, body, KEY_A).status_code == 400


def test_accepts_then_reports_duplicate_and_stores_one_pending_event(
    app_client: TestClient, adapters: Adapters, source_a: Source
) -> None:
    first = push(app_client, source_a.id, BODY, KEY_A)
    second = push(app_client, source_a.id, BODY, KEY_A)
    assert first.status_code == second.status_code == 202
    assert first.json()["duplicate"] is False
    assert second.json() == {"raw_event_id": None, "duplicate": True}
    event = adapters.queue.get(first.json()["raw_event_id"])
    assert event is not None
    assert event.status == EventStatus.PENDING
    assert event.tenant_id == source_a.tenant_id
    payload = json.loads(BODY)
    assert event.external_event_id == CONNECTORS[SourceType.PLAYSTORE].external_event_id(payload)
    assert adapters.queue.counts()[EventStatus.PENDING] == 1


def test_storage_down_is_503_never_202(
    app_client: TestClient, adapters: Adapters, source_a: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(*_args: object) -> bool:
        statement = "INSERT"
        raise OperationalError(statement, {}, Exception("disk I/O error"))

    monkeypatch.setattr(adapters.queue, "enqueue", down)
    response = push(app_client, source_a.id, BODY, KEY_A)
    assert response.status_code == 503
    assert response.json() == {"detail": "storage unavailable"}
