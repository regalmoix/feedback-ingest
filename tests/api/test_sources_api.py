import httpx2
import pytest
from fastapi.testclient import TestClient

from api.conftest import KEY_A, KEY_B, SECRET, fixture_body, push
from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.enums import SourceMode, SourceType
from feedback_ingest.domain.models import Source

FORUM = {"base_url": "https://forum.example.test", "start_after": "2026-02-01"}


def create(client: TestClient, api_key: str, **body: object) -> httpx2.Response:
    return client.post("/v1/sources", json=body, headers={"X-API-Key": api_key})


@pytest.mark.usefixtures("source_a")
def test_push_secret_is_generated_shown_once_and_masked_after(app_client: TestClient) -> None:
    created = create(app_client, KEY_A, type="playstore", name="acme-android", mode="push")
    assert created.status_code == 201
    body = created.json()
    assert len(body["webhook_secret"]) == 64
    view = app_client.get(f"/v1/sources/{body['id']}", headers={"X-API-Key": KEY_A}).json()
    assert view["webhook_secret"] == "***"  # noqa: S105  the mask, not a secret
    assert (view["enabled"], view["cursor"]) == (True, None)
    review = fixture_body(SourceType.PLAYSTORE, "review")
    assert push(app_client, body["id"], review, KEY_A, body["webhook_secret"]).status_code == 202


@pytest.mark.usefixtures("source_a")
def test_given_secret_and_config_are_kept(app_client: TestClient, adapters: Adapters) -> None:
    body = create(
        app_client, KEY_A, type="discourse", name="forum", mode="pull", config=FORUM
    ).json()
    assert (body["config"], body["webhook_secret"]) == (FORUM, None)
    [pulled] = adapters.sources.list_by_mode(SourceMode.PULL)
    assert (pulled.id, pulled.config) == (body["id"], FORUM)
    own = create(app_client, KEY_A, type="twitter", name="t", mode="push", webhook_secret=SECRET)
    assert own.json()["webhook_secret"] == SECRET


@pytest.mark.usefixtures("source_a")
def test_pull_source_missing_a_config_key_is_422_naming_it(app_client: TestClient) -> None:
    config = {"start_after": "2026-02-01"}
    response = create(app_client, KEY_A, type="discourse", name="f", mode="pull", config=config)
    assert response.status_code == 422
    assert "base_url" in response.json()["detail"]


@pytest.mark.usefixtures("source_a")
def test_pull_source_for_a_push_only_type_is_422(app_client: TestClient) -> None:
    response = create(app_client, KEY_A, type="playstore", name="p", mode="pull", config=FORUM)
    assert response.status_code == 422
    assert "cannot pull" in response.json()["detail"]


@pytest.mark.usefixtures("source_b")
def test_other_tenants_sources_are_invisible(app_client: TestClient, source_a: Source) -> None:
    url, theirs = f"/v1/sources/{source_a.id}", {"X-API-Key": KEY_B}
    assert app_client.get(url, headers=theirs).status_code == 404
    assert app_client.patch(url, json={"enabled": False}, headers=theirs).status_code == 404
    listed = app_client.get("/v1/sources", headers=theirs).json()
    assert [s["id"] for s in listed] == ["src-tenant-b-playstore"]
    assert app_client.get("/v1/sources").status_code == 401


@pytest.mark.usefixtures("source_a")
def test_disabled_source_leaves_list_by_mode(app_client: TestClient, adapters: Adapters) -> None:
    created = create(app_client, KEY_A, type="discourse", name="f", mode="pull", config=FORUM)
    url, mine = f"/v1/sources/{created.json()['id']}", {"X-API-Key": KEY_A}
    patched = app_client.patch(url, json={"enabled": False}, headers=mine)
    assert patched.json()["enabled"] is False
    assert adapters.sources.list_by_mode(SourceMode.PULL) == []
    assert app_client.get(url, headers=mine).json()["enabled"] is False
