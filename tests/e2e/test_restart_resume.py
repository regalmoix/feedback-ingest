import json

from api.conftest import KEY_A, app_state, fixture_body, push, seed_source
from fastapi.testclient import TestClient

from e2e.conftest import wait_until
from feedback_ingest.config import Settings
from feedback_ingest.domain.enums import EventStatus, SourceType
from feedback_ingest.main import create_app


def test_events_accepted_before_a_restart_are_processed_after_it(settings: Settings) -> None:
    review = json.loads(fixture_body(SourceType.PLAYSTORE, "review"))
    bodies = [json.dumps(review | {"reviewId": f"review-{n}"}).encode() for n in range(3)]
    accept_only = settings.model_copy(update={"worker_enabled": False})
    with TestClient(create_app(accept_only)) as client:
        adapters = app_state(client).adapters
        source = seed_source(adapters, "tenant-a", KEY_A)
        for body in bodies:
            assert push(client, source.id, body, KEY_A).status_code == 202
        assert adapters.queue.counts()[EventStatus.PENDING] == 3

    with TestClient(create_app(settings)) as client:
        adapters = app_state(client).adapters
        wait_until(lambda: adapters.queue.counts()[EventStatus.PROCESSED] == 3)
        assert len(adapters.feedback.list_for_tenant(source.tenant_id)) == 3
