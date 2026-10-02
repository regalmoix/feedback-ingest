from fastapi.testclient import TestClient
from helpers import KEY_A, MINE, app_state, fixture_body, push, seed_source

from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.enums import SourceType


def test_a_custom_batch_is_one_delivery_and_three_records_of_three_kinds(
    app_client: TestClient, adapters: Adapters
) -> None:
    source = seed_source(adapters, "tenant-a", KEY_A, SourceType.CUSTOM)
    body = fixture_body(SourceType.CUSTOM, "batch")
    first, again = push(app_client, source.id, body), push(app_client, source.id, body)
    assert (first.status_code, again.status_code) == (202, 202)
    assert (first.json()["duplicate"], again.json()["duplicate"]) == (False, True)
    app_state(app_client).worker.run_once()
    records = app_client.get("/v1/records", headers=MINE).json()
    assert [(r["external_id"], r["kind"]) for r in records] == [
        ("lumenote-review-0001", "review"),
        ("lumenote-chat-0001", "conversation"),
        ("lumenote-nps-0001", "survey"),
    ]
    [survey] = app_client.get("/v1/records?kind=survey", headers=MINE).json()
    assert survey["metadata"]["score"] == 8
