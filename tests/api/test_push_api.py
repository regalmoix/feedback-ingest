import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import KEY_A, KEY_B, app_state, fixture_body, push
from sqlalchemy import exc as sa_exc

from feedback_ingest.api.deps import Adapters
from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.enums import EventStatus, SourceMode, SourceType
from feedback_ingest.domain.models import Source
from feedback_ingest.services.ingestion import AcceptResult

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


def test_pull_source_without_a_secret_rejects_unsigned_pushes(
    app_client: TestClient, adapters: Adapters, source_a: Source
) -> None:
    update = {"id": "pull", "mode": SourceMode.PULL, "webhook_secret": None}
    adapters.sources.add(source_a.model_copy(update=update))
    headers = {"X-API-Key": KEY_A}  # no X-Signature
    response = app_client.post("/v1/sources/pull/events", content=BODY, headers=headers)
    assert response.status_code == 401
    assert sum(adapters.queue.counts().values()) == 0


@pytest.mark.parametrize("body", [b"[1, 2]", b'"text"', b"{not json", b"\xff", b"[" * 100_000])
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


def test_accept_runs_off_the_event_loop(
    app_client: TestClient, source_a: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingestion = app_state(app_client).ingestion
    accept = ingestion.accept
    calls: list[str] = []

    def off_loop(source: Source, payload: Mapping[str, Any]) -> AcceptResult:
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        calls.append(source.id)
        return accept(source, payload)

    monkeypatch.setattr(ingestion, "accept", off_loop)
    assert push(app_client, source_a.id, BODY, KEY_A).status_code == 202
    assert calls == [source_a.id]


DOWN = [
    sa_exc.OperationalError("INSERT", {}, Exception("disk I/O error")),
    sa_exc.InterfaceError("INSERT", {}, Exception("connection closed")),
    sa_exc.TimeoutError("pool exhausted"),
]


@pytest.mark.parametrize("error", DOWN)
def test_storage_down_is_503_never_202_and_logged(
    app_client: TestClient,
    source_a: Source,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    def down(*_args: object) -> bool:
        raise error

    monkeypatch.setattr(app_state(app_client).adapters.queue, "enqueue", down)
    response = push(app_client, source_a.id, BODY, KEY_A)
    assert (response.status_code, response.json()) == (503, {"detail": "storage unavailable"})
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert record.getMessage() == f"storage unavailable: POST /v1/sources/{source_a.id}/events"
    assert record.exc_info == (type(error), error, error.__traceback__)
