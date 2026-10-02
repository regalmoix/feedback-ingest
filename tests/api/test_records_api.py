import pytest
from fastapi.testclient import TestClient

from api.conftest import KEY_A, MINE, THEIRS, app_state, fixture_body, push
from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.enums import SourceType
from feedback_ingest.domain.models import Source

REVIEW, POST, DELETED = "gp:AOqpTEST-review-0001", "9001", "9002"


@pytest.fixture
def ids(app_client: TestClient, adapters: Adapters, source_a: Source) -> dict[str, str]:
    forum = source_a.model_copy(update={"id": "src-forum", "type": SourceType.DISCOURSE})
    adapters.sources.add(forum)
    push(app_client, source_a.id, fixture_body(SourceType.PLAYSTORE, "review"), KEY_A)
    for name in ("post", "post_deleted"):
        push(app_client, forum.id, fixture_body(SourceType.DISCOURSE, name), KEY_A)
    app_state(app_client).worker.run_once()
    stored = adapters.feedback.list_for_tenant(source_a.tenant_id, include_deleted=True)
    return {r.external_id: r.id for r in stored}


def external_ids(client: TestClient, query: str, headers: dict[str, str] = MINE) -> list[str]:
    response = client.get(f"/v1/records?{query}", headers=headers)
    assert response.status_code == 200, response.text
    return [r["external_id"] for r in response.json()]


@pytest.mark.usefixtures("ids")
def test_filters_by_source_kind_and_since(app_client: TestClient) -> None:
    assert external_ids(app_client, "") == [REVIEW, POST]
    assert external_ids(app_client, "source_id=src-forum") == [POST]
    assert external_ids(app_client, "kind=review") == [REVIEW]
    assert external_ids(app_client, "since=2026-02-05T00:00:00") == [POST]
    assert external_ids(app_client, "since=2026-02-10T14:00:00%2B05:30") == [POST]


@pytest.mark.usefixtures("ids")
def test_tombstones_are_hidden_unless_asked_for(app_client: TestClient) -> None:
    assert external_ids(app_client, "include_deleted=true") == [REVIEW, POST, DELETED]
    assert external_ids(app_client, "include_deleted=true&limit=1") == [REVIEW]


@pytest.mark.usefixtures("ids")
@pytest.mark.parametrize(
    "query", ["limit=0", "limit=501", "kind=tweet", "since=soon", "knd=review", "tenant_id=x"]
)
def test_bad_query_values_are_422(app_client: TestClient, query: str) -> None:
    assert app_client.get(f"/v1/records?{query}", headers=MINE).status_code == 422


def test_get_one_record_hides_tombstones_by_default(
    app_client: TestClient, ids: dict[str, str]
) -> None:
    record = app_client.get(f"/v1/records/{ids[REVIEW]}", headers=MINE).json()
    assert record["metadata"]["source_type"] == "playstore"
    assert record["rating"] == 2
    deleted = f"/v1/records/{ids[DELETED]}"
    assert app_client.get(deleted, headers=MINE).status_code == 404
    assert app_client.get(f"{deleted}?include_deleted=true", headers=MINE).status_code == 200
    assert app_client.get("/v1/records/missing", headers=MINE).status_code == 404


@pytest.mark.usefixtures("source_b")
def test_other_tenant_cannot_read_records(app_client: TestClient, ids: dict[str, str]) -> None:
    assert app_client.get(f"/v1/records/{ids[REVIEW]}", headers=THEIRS).status_code == 404
    response = app_client.get("/v1/records?source_id=src-forum", headers=THEIRS)
    assert response.status_code == 404
    assert external_ids(app_client, "include_deleted=true", THEIRS) == []
