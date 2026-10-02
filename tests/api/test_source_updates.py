import pytest
from fastapi.testclient import TestClient
from helpers import MINE

FORUM = {"base_url": "https://forum.example.test", "start_after": "2026-02-01"}
PUSH = {"type": "twitter", "name": "t", "mode": "push"}


@pytest.mark.usefixtures("source_a")
def test_patch_merges_config_and_checks_the_result(app_client: TestClient) -> None:
    body = {"type": "discourse", "name": "f", "mode": "pull", "config": FORUM}
    created = app_client.post("/v1/sources", json=body, headers=MINE)
    url = f"/v1/sources/{created.json()['id']}"
    narrowed = FORUM | {"window_days": "2"}
    ok = app_client.patch(url, json={"config": {"window_days": "2"}}, headers=MINE)
    assert (ok.status_code, ok.json()["config"]) == (200, narrowed)
    for bad in ({"window_days": "32"}, {"base_url": "http://127.0.0.1"}):
        assert app_client.patch(url, json={"config": bad}, headers=MINE).status_code == 422
    assert app_client.get(url, headers=MINE).json()["config"] == narrowed
    both = app_client.patch(url, json={"config": {}, "enabled": False}, headers=MINE).json()
    assert (both["config"], both["enabled"]) == (narrowed, False)
    assert app_client.patch(url, json={"cursor": "x"}, headers=MINE).status_code == 422


@pytest.mark.usefixtures("source_a")
@pytest.mark.parametrize(
    "body",
    [
        {"type": "discourse", "mode": "pull", "config": FORUM, "webhook_secret": "s" * 16},
        PUSH | {"webhook_secret": "too-short"},
        PUSH | {"webhook_secret": ""},  # an empty secret is not a secret
        PUSH | {"name": "   "},
        PUSH | {"name": "x" * 201},
    ],
)
def test_bad_source_bodies_are_422(app_client: TestClient, body: dict[str, object]) -> None:
    assert (
        app_client.post("/v1/sources", json={"name": "f"} | body, headers=MINE).status_code == 422
    )


@pytest.mark.usefixtures("source_a")
def test_a_tenant_chosen_secret_of_16_chars_is_kept(app_client: TestClient) -> None:
    created = app_client.post("/v1/sources", json=PUSH | {"webhook_secret": "s" * 16}, headers=MINE)
    assert (created.status_code, created.json()["webhook_secret"]) == (201, "s" * 16)
