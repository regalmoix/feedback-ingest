from fastapi.testclient import TestClient
from helpers import KEY_A, app_state, fixture_body, push, seed_source, wait_until

from feedback_ingest.config import Settings
from feedback_ingest.domain.enums import EventStatus, SourceType
from feedback_ingest.main import create_app


def test_the_same_webhook_twice_gives_one_record(settings: Settings) -> None:
    body = fixture_body(SourceType.PLAYSTORE, "review")
    with TestClient(create_app(settings)) as client:
        adapters = app_state(client).adapters
        source = seed_source(adapters, "tenant-a", KEY_A)
        assert [push(client, source.id, body, KEY_A).status_code for _ in range(2)] == [202, 202]
        wait_until(lambda: adapters.queue.counts()[EventStatus.PROCESSED] == 1)
        records = adapters.feedback.list_for_tenant(source.tenant_id)
        assert sum(adapters.queue.counts().values()) == 1
    assert [r.external_id for r in records] == ["gp:AOqpTEST-review-0001"]
