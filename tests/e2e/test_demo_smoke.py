import pytest
from api.conftest import memory_adapters
from fastapi.testclient import TestClient

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.config import Settings
from feedback_ingest.main import create_app
from scripts.seed_lib import seed

TOKEN = "bootstrap-test"  # noqa: S105  synthetic test token
EXPECTED = {
    "forum": ("discourse", "pull"),
    "android": ("playstore", "push"),
    "ios-wrapper": ("playstore", "push"),
    "twitter": ("twitter", "push"),
    "intercom": ("intercom", "push"),
}


def test_seed_creates_two_tenants_with_isolated_sources(
    clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FI_SCHEDULER_ENABLED", "false")  # keep a future scheduler off the network
    settings = Settings(worker_enabled=False, bootstrap_token=TOKEN)
    with TestClient(create_app(settings, adapters=memory_adapters(clock))) as client:
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
