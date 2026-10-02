import httpx2
import pytest
from fastapi.testclient import TestClient
from helpers import TOKEN, client_for

from feedback_ingest.api.deps import Adapters
from feedback_ingest.config import DEFAULT_BOOTSTRAP_TOKEN


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
        assert len(tenant["api_key"]) >= 43  # token_urlsafe(32): 256 bits
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
        for name in ("", "   ", "x" * 201):
            assert bootstrap(client, TOKEN, name=name).status_code == 422


@pytest.mark.parametrize("token", [DEFAULT_BOOTSTRAP_TOKEN, ""])
def test_the_default_or_an_empty_token_refuses_bootstrap(
    adapters: Adapters, caplog: pytest.LogCaptureFixture, token: str
) -> None:
    with client_for(adapters, bootstrap_token=token) as client:
        assert bootstrap(client, token).status_code == 401
    assert "POST /admin/tenants is refused: set FI_BOOTSTRAP_TOKEN" in caplog.text
