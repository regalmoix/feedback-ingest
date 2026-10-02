import pytest
from fastapi.testclient import TestClient

from feedback_ingest.api.deps import Adapters
from feedback_ingest.config import Settings
from feedback_ingest.main import create_app

TOKEN = "bootstrap-test"  # noqa: S105  synthetic test token


def bootstrap(client: TestClient, token: str | None) -> int:
    headers = {"X-Bootstrap-Token": token} if token is not None else {}
    return client.post("/admin/tenants", json={"name": "acme"}, headers=headers).status_code


def test_bootstrap_token_is_required_and_the_api_key_works(
    adapters: Adapters, caplog: pytest.LogCaptureFixture
) -> None:
    settings = Settings(worker_enabled=False, bootstrap_token=TOKEN)
    with TestClient(create_app(settings, adapters=adapters)) as client:
        assert [bootstrap(client, t) for t in (None, "", "wrong")] == [401, 401, 401]
        created = client.post(
            "/admin/tenants", json={"name": "acme"}, headers={"X-Bootstrap-Token": TOKEN}
        )
        assert created.status_code == 201
        tenant = created.json()
        assert tenant["name"] == "acme"
        sources = client.get("/v1/sources", headers={"X-API-Key": tenant["api_key"]})
        assert (sources.status_code, sources.json()) == (200, [])
    assert "FI_BOOTSTRAP_TOKEN" not in caplog.text


def test_default_token_warns_and_empty_token_locks_bootstrap(
    adapters: Adapters, caplog: pytest.LogCaptureFixture
) -> None:
    with TestClient(create_app(Settings(worker_enabled=False), adapters=adapters)):
        pass
    assert "FI_BOOTSTRAP_TOKEN is the default" in caplog.text
    settings = Settings(worker_enabled=False, bootstrap_token="")
    with TestClient(create_app(settings, adapters=adapters)) as client:
        assert bootstrap(client, "") == 401
