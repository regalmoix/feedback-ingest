import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import KEY_A, app_state, fixture_body, push
from sqlalchemy import exc as sa_exc

from feedback_ingest.api.deps import Adapters
from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.enums import EventStatus, SourceMode, SourceType
from feedback_ingest.domain.models import Source
from feedback_ingest.services.ingestion import AcceptResult

BODY = fixture_body(SourceType.PLAYSTORE, "review")


def test_no_api_key_is_needed_but_a_signature_is(
    app_client: TestClient, adapters: Adapters, source_a: Source
) -> None:
    url = f"/v1/sources/{source_a.id}/events"
    assert app_client.post(url, content=BODY).status_code == 401
    assert app_client.post(url, content=BODY, headers={"X-API-Key": KEY_A}).status_code == 401
    assert push(app_client, source_a.id, BODY, "wrong").status_code == 401
    assert sum(adapters.queue.counts().values()) == 0
    accepted = push(app_client, source_a.id, BODY)
    assert accepted.status_code == 202
    event = adapters.queue.get(accepted.json()["raw_event_id"])
    assert event is not None
    assert event.tenant_id == source_a.tenant_id  # from the source row


def test_unknown_source_is_404(app_client: TestClient) -> None:
    assert push(app_client, "src-unknown", BODY).status_code == 404


def test_only_push_sources_take_webhooks_and_the_signature_is_checked_before_state(
    app_client: TestClient, adapters: Adapters, source_a: Source
) -> None:
    adapters.sources.add(source_a.model_copy(update={"id": "pulled", "mode": SourceMode.PULL}))
    pulled = push(app_client, "pulled", BODY)
    assert (pulled.status_code, pulled.json()) == (
        409,
        {"detail": "source does not accept webhooks"},
    )
    adapters.sources.set_enabled(source_a.id, source_a.tenant_id, False)
    assert push(app_client, source_a.id, BODY, "a-wrong-secret-0000").status_code == 401
    assert push(app_client, source_a.id, BODY).status_code == 409


@pytest.mark.parametrize("body", [b"[1, 2]", b'"text"', b"{not json", b"\xff", b"[" * 100_000])
def test_body_that_is_not_a_json_object_is_400(
    app_client: TestClient, source_a: Source, body: bytes
) -> None:
    assert push(app_client, source_a.id, body).status_code == 400


def test_accepts_then_reports_duplicate_and_stores_one_pending_event(
    app_client: TestClient, adapters: Adapters, source_a: Source
) -> None:
    first = push(app_client, source_a.id, BODY)
    second = push(app_client, source_a.id, BODY)
    assert first.status_code == second.status_code == 202
    assert first.json()["duplicate"] is False
    assert second.json() == {"raw_event_id": first.json()["raw_event_id"], "duplicate": True}
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
    assert push(app_client, source_a.id, BODY).status_code == 202
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
    response = push(app_client, source_a.id, BODY)
    assert (response.status_code, response.json()) == (503, {"detail": "storage unavailable"})
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert record.getMessage() == f"storage unavailable: POST /v1/sources/{source_a.id}/events"
    assert record.exc_info == (type(error), error, error.__traceback__)
    assert vars(record)["source_id"] == source_a.id
