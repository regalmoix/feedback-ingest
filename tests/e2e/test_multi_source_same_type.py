from fastapi.testclient import TestClient
from helpers import fixture_body, push, wait_until

from feedback_ingest.config import Settings
from feedback_ingest.domain.enums import SourceType
from feedback_ingest.main import create_app
from scripts.seed_lib import create_source, create_tenant


def test_two_playstore_apps_with_the_same_review_give_two_records(settings: Settings) -> None:
    body = fixture_body(SourceType.PLAYSTORE, "review")
    with TestClient(create_app(settings)) as client:
        key = create_tenant(client, settings.bootstrap_token, "acme")["api_key"]
        apps = [create_source(client, key, "playstore", name) for name in ("android", "ios")]
        for app in apps:
            assert push(client, app["id"], body, app["webhook_secret"]).status_code == 202

        def records() -> list[dict[str, str]]:
            found: list[dict[str, str]] = client.get(
                "/v1/records?kind=review", headers={"X-API-Key": key}
            ).json()
            return found

        wait_until(lambda: len(records()) == 2)
        got = records()
    assert sorted(r["source_id"] for r in got) == sorted(app["id"] for app in apps)
    assert {r["external_id"] for r in got} == {"gp:AOqpTEST-review-0001"}
