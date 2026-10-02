import pytest
from helpers import TOKEN, client_for

from feedback_ingest.api.deps import Adapters
from scripts.seed_lib import TENANTS, create_source, create_tenant, seed_tenant

EXPECTED = {
    "lumenote": {
        "lumenote-community": ("discourse", "pull"),
        "lumenote-android": ("playstore", "push"),
        "lumenote-android-beta": ("playstore", "push"),
        "lumenote-surveys": ("custom", "push"),
    },
    "brightwave": {
        "brightwave-support": ("intercom", "push"),
        "brightwave-x": ("twitter", "push"),
        "brightwave-nps": ("custom", "push"),
    },
}


def test_seed_creates_two_tenants_with_isolated_sources(adapters: Adapters) -> None:
    with client_for(adapters, bootstrap_token=TOKEN) as client:
        seeded = {name: seed_tenant(client, TOKEN, name) for name in TENANTS}
        assert list(seeded) == ["lumenote", "brightwave"]
        for name, tenant in seeded.items():
            sources = tenant["sources"]
            assert {k: (s["type"], s["mode"]) for k, s in sources.items()} == EXPECTED[name]
            assert all(
                (s["webhook_secret"] is None) == (s["mode"] == "pull") for s in sources.values()
            )
            listed = client.get("/v1/sources", headers={"X-API-Key": tenant["api_key"]}).json()
            assert sorted(s["id"] for s in listed) == sorted(s["id"] for s in sources.values())
            assert {s["webhook_secret"] for s in listed if s["mode"] == "push"} == {"***"}
        assert len(seeded["lumenote"]["sources"]["lumenote-android"]["webhook_secret"]) == 64
        forum = seeded["lumenote"]["sources"]["lumenote-community"]["id"]
        brightwave = {"X-API-Key": seeded["brightwave"]["api_key"]}
        assert client.get(f"/v1/sources/{forum}", headers=brightwave).status_code == 404


def test_seed_raises_with_the_server_detail_on_a_non_2xx(adapters: Adapters) -> None:
    with client_for(adapters, bootstrap_token=TOKEN) as client:
        with pytest.raises(RuntimeError, match=r"POST /admin/tenants: 401 .*X-Bootstrap-Token"):
            create_tenant(client, "wrong", "lumenote")
        with pytest.raises(RuntimeError, match=r"POST /v1/sources: 401 .*X-API-Key"):
            create_source(client, "not-a-key", "playstore", "lumenote-android")
