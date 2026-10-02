import httpx2
import pytest
from fastapi.testclient import TestClient
from helpers import client_for

from feedback_ingest.api.deps import Adapters

TOKEN = "bootstrap-test"  # noqa: S105  synthetic test token


def bootstrap(client: TestClient, token: str | None, name: str = "acme") -> httpx2.Response:
    headers = {"X-Bootstrap-Token": token} if token is not None else {}
    return client.post("/admin/tenants", json={"name": name}, headers=headers)


def test_bootstrap_token_is_required_and_the_api_key_works(
    adapters: Adapters, caplog: pytest.LogCaptureFixture
) -> None:
    with client_for(adapters, bootstrap_token=TOKEN) as client:
        assert [bootstrap(client, t).status_code for t in (None, "", "wrong")] == [401, 401, 401]
        created = bootstrap(client, TOKEN)
        assert created.status_code == 201
        tenant = created.json()
        assert tenant["name"] == "acme"
        sources = client.get("/v1/sources", headers={"X-API-Key": tenant["api_key"]})
        assert (sources.status_code, sources.json()) == (200, [])
    assert "FI_BOOTSTRAP_TOKEN" not in caplog.text


def test_tenant_names_are_unique_and_non_empty(adapters: Adapters) -> None:
    with client_for(adapters, bootstrap_token=TOKEN) as client:
        assert bootstrap(client, TOKEN).status_code == 201
        duplicate = bootstrap(client, TOKEN)
        assert (duplicate.status_code, duplicate.json()) == (
            409,
            {"detail": "tenant 'acme' exists"},
        )
        assert bootstrap(client, TOKEN, name="").status_code == 422


def test_default_token_warns_and_empty_token_locks_bootstrap(
    adapters: Adapters, caplog: pytest.LogCaptureFixture
) -> None:
    with client_for(adapters):
        pass
    assert "FI_BOOTSTRAP_TOKEN is the default" in caplog.text
    with client_for(adapters, bootstrap_token="") as client:
        assert bootstrap(client, "").status_code == 401
    assert "FI_BOOTSTRAP_TOKEN is empty; POST /admin/tenants is disabled" in caplog.text
