from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from helpers import KEY_A, KEY_B, app_state, fixture_body, push

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.api.deps import Adapters
from feedback_ingest.config import Settings
from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.enums import EventStatus, SourceType
from feedback_ingest.domain.errors import TransientError
from feedback_ingest.domain.models import FeedbackRecord, Source
from feedback_ingest.main import create_app

MALFORMED = fixture_body(SourceType.PLAYSTORE, "malformed")
REVIEW = fixture_body(SourceType.PLAYSTORE, "review")


def _dead_event(client: TestClient, source: Source, api_key: str) -> str:
    event_id: str = push(client, source.id, MALFORMED, api_key).json()["raw_event_id"]
    app_state(client).worker.run_once()
    return event_id


@pytest.mark.usefixtures("source_b")
def test_lists_dead_events_for_the_callers_tenant_only(
    app_client: TestClient, source_a: Source
) -> None:
    event_id = _dead_event(app_client, source_a, KEY_A)
    mine = app_client.get("/admin/raw-events", headers={"X-API-Key": KEY_A}).json()
    theirs = app_client.get("/admin/raw-events?status=dead", headers={"X-API-Key": KEY_B}).json()
    assert [e["id"] for e in mine] == [event_id]
    assert mine[0]["status"] == "dead"
    assert "payload" not in mine[0]
    assert theirs == []


@pytest.mark.usefixtures("source_b")
def test_get_raw_event_includes_payload_and_is_tenant_checked(
    app_client: TestClient, source_a: Source
) -> None:
    event_id = _dead_event(app_client, source_a, KEY_A)
    url = f"/admin/raw-events/{event_id}"
    detail = app_client.get(url, headers={"X-API-Key": KEY_A}).json()
    assert detail["payload"]["reviewId"] == "gp:AOqpTEST-review-0002"
    assert app_client.get(url, headers={"X-API-Key": KEY_B}).status_code == 404


@pytest.mark.usefixtures("source_b")
def test_replay_of_unknown_or_foreign_event_is_404(
    app_client: TestClient, source_a: Source
) -> None:
    event_id = _dead_event(app_client, source_a, KEY_A)
    for path, key in (("missing", KEY_A), (event_id, KEY_B)):
        response = app_client.post(f"/admin/raw-events/{path}/replay", headers={"X-API-Key": key})
        assert response.status_code == 404


def test_replay_of_a_processing_event_is_409(
    app_client: TestClient, adapters: Adapters, source_a: Source
) -> None:
    event_id = push(app_client, source_a.id, REVIEW, KEY_A).json()["raw_event_id"]
    adapters.queue.claim(adapters.clock.now(), 30, 10)
    response = app_client.post(f"/admin/raw-events/{event_id}/replay", headers={"X-API-Key": KEY_A})
    assert response.status_code == 409


@pytest.fixture
def flaky_client(adapters: Adapters) -> Iterator[TestClient]:
    settings = Settings(worker_enabled=False, scheduler_enabled=False, max_attempts=2)
    with TestClient(create_app(settings, adapters=adapters)) as client:
        yield client


def test_transient_failures_go_dead_then_replay_processes_after_the_fix(
    flaky_client: TestClient,
    adapters: Adapters,
    clock: FixedClock,
    source_a: Source,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def flaky(*_args: object) -> list[FeedbackRecord]:
        msg = "upstream timeout"
        raise TransientError(msg)

    monkeypatch.setattr(CONNECTORS[SourceType.PLAYSTORE], "transform", flaky)
    worker = app_state(flaky_client).worker
    event_id = push(flaky_client, source_a.id, REVIEW, KEY_A).json()["raw_event_id"]
    worker.run_once()
    assert adapters.queue.counts()[EventStatus.FAILED] == 1
    clock.advance(2)
    worker.run_once()
    assert adapters.queue.counts()[EventStatus.DEAD] == 1

    monkeypatch.undo()
    headers = {"X-API-Key": KEY_A}
    replay = flaky_client.post(f"/admin/raw-events/{event_id}/replay", headers=headers)
    assert replay.json() == {"status": "pending"}
    assert worker.run_once() == 1
    counts = flaky_client.get("/admin/queue", headers=headers).json()
    assert counts == {"pending": 0, "processing": 0, "processed": 1, "failed": 0, "dead": 0}
    assert len(adapters.feedback.list_for_tenant(source_a.tenant_id)) == 1


@pytest.mark.usefixtures("source_b")
def test_queue_counts_are_tenant_scoped(app_client: TestClient, source_a: Source) -> None:
    push(app_client, source_a.id, REVIEW, KEY_A)
    for key, pending in ((KEY_A, 1), (KEY_B, 0)):
        assert (
            app_client.get("/admin/queue", headers={"X-API-Key": key}).json()["pending"] == pending
        )


@pytest.mark.usefixtures("source_a")
def test_list_limit_above_500_is_422(app_client: TestClient) -> None:
    response = app_client.get("/admin/raw-events?limit=501", headers={"X-API-Key": KEY_A})
    assert response.status_code == 422
