import pytest
from fastapi.testclient import TestClient
from helpers import memory_adapters

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.config import Settings
from feedback_ingest.main import create_app
from scripts.seed_lib import create_source, create_tenant, seed

TOKEN = "bootstrap-test"  # noqa: S105  synthetic test token
EXPECTED = {
    "forum": ("discourse", "pull"),
    "android": ("playstore", "push"),
    "ios-wrapper": ("playstore", "push"),
    "twitter": ("twitter", "push"),
    "intercom": ("intercom", "push"),
}


SETTINGS = Settings(worker_enabled=False, scheduler_enabled=False, bootstrap_token=TOKEN)


def test_seed_creates_two_tenants_with_isolated_sources(clock: FixedClock) -> None:
    with TestClient(create_app(SETTINGS, adapters=memory_adapters(clock))) as client:
        seeded = seed(client, TOKEN)
        assert list(seeded) == ["acme", "globex"]
        for name, tenant in seeded.items():
            sources = tenant["sources"]
            assert {k: (s["type"], s["mode"]) for k, s in sources.items()} == {
                f"{name}-{suffix}": shape for suffix, shape in EXPECTED.items()
            }
            assert sources[f"{name}-forum"]["webhook_secret"] is None
            assert len(sources[f"{name}-android"]["webhook_secret"]) == 64
            listed = client.get("/v1/sources", headers={"X-API-Key": tenant["api_key"]}).json()
            assert sorted(s["id"] for s in listed) == sorted(s["id"] for s in sources.values())
            assert {s["webhook_secret"] for s in listed} == {"***", None}
        acme_forum = seeded["acme"]["sources"]["acme-forum"]["id"]
        globex = {"X-API-Key": seeded["globex"]["api_key"]}
        assert client.get(f"/v1/sources/{acme_forum}", headers=globex).status_code == 404


def test_seed_raises_with_the_server_detail_on_a_non_2xx(clock: FixedClock) -> None:
    with TestClient(create_app(SETTINGS, adapters=memory_adapters(clock))) as client:
        with pytest.raises(RuntimeError, match=r"POST /admin/tenants: 401 .*X-Bootstrap-Token"):
            create_tenant(client, "wrong", "acme")
        with pytest.raises(RuntimeError, match=r"POST /v1/sources: 401 .*X-API-Key"):
            create_source(client, "not-a-key", "playstore", "acme-android")
