import json

from fastapi.testclient import TestClient
from helpers import KEY_A, KEY_B, MINE, app_state, fixture_body, load, push

from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.enums import SourceType
from feedback_ingest.domain.models import Source

MALFORMED = fixture_body(SourceType.PLAYSTORE, "malformed")
REVIEW = fixture_body(SourceType.PLAYSTORE, "review")


def _counts(client: TestClient, key: str) -> dict[str, int]:
    counts: dict[str, int] = client.get("/admin/queue", headers={"X-API-Key": key}).json()
    return counts


def test_bulk_replay_requeues_only_the_callers_matching_rows(
    app_client: TestClient, adapters: Adapters, source_a: Source, source_b: Source
) -> None:
    other_a = source_a.model_copy(update={"id": "src-a-other"})
    adapters.sources.add(other_a)
    for source in (source_a, other_a, source_b):
        push(app_client, source.id, MALFORMED)
    push(app_client, source_a.id, REVIEW)
    app_state(app_client).worker.run_once()
    assert (_counts(app_client, KEY_A)["dead"], _counts(app_client, KEY_B)["dead"]) == (2, 1)

    replay = f"/admin/raw-events/replay?source_id={source_a.id}"
    assert app_client.post(replay, headers=MINE).json() == {"requeued": 1}
    assert (_counts(app_client, KEY_A)["dead"], _counts(app_client, KEY_A)["pending"]) == (1, 1)
    assert app_client.post("/admin/raw-events/replay", headers=MINE).json() == {"requeued": 1}
    assert _counts(app_client, KEY_B)["dead"] == 1
    processed = "/admin/raw-events/replay?status=processed&limit=1"
    assert app_client.post(processed, headers=MINE).json() == {"requeued": 1}
    assert _counts(app_client, KEY_A) == {
        "pending": 3, "processing": 0, "processed": 0, "failed": 0, "dead": 0
    }  # fmt: skip
    assert (
        app_client.post("/admin/raw-events/replay?status=pending", headers=MINE).status_code == 422
    )


def test_responses_leave_out_the_tenant_id(app_client: TestClient, source_a: Source) -> None:
    event_id = push(app_client, source_a.id, REVIEW).json()["raw_event_id"]
    detail = app_client.get(f"/admin/raw-events/{event_id}", headers=MINE).json()
    assert detail["payload"]["reviewId"] == "gp:AOqpTEST-review-0001"
    assert "tenant_id" not in detail
    app_state(app_client).worker.run_once()
    [record] = app_client.get("/v1/records", headers=MINE).json()
    assert "tenant_id" not in record
    assert "tenant_id" not in app_client.get(f"/v1/records/{record['id']}", headers=MINE).json()


def test_the_dead_list_shows_why_and_honours_limit(
    app_client: TestClient, source_a: Source
) -> None:
    for n in range(2):
        body = load(SourceType.PLAYSTORE, "malformed") | {"n": n}
        push(app_client, source_a.id, json.dumps(body).encode())
    app_state(app_client).worker.run_once()
    listed = app_client.get("/admin/raw-events", headers=MINE).json()
    assert len(listed) == 2
    assert all("comments" in e["error"] for e in listed)
    assert len(app_client.get("/admin/raw-events?limit=1", headers=MINE).json()) == 1
