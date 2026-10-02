from fastapi.testclient import TestClient
from helpers import KEY_A, app_state, fixture_body, push, seed_source, wait_until

from feedback_ingest.config import Settings
from feedback_ingest.domain.enums import EventStatus, SourceType
from feedback_ingest.domain.models import RawEvent
from feedback_ingest.main import create_app


def test_replaying_a_malformed_payload_runs_it_again_and_it_goes_dead_again(
    settings: Settings,
) -> None:
    with TestClient(create_app(settings)) as client:
        queue = app_state(client).adapters.queue
        source = seed_source(app_state(client).adapters, "tenant-a", KEY_A)
        body = fixture_body(SourceType.PLAYSTORE, "malformed")
        event_id = push(client, source.id, body).json()["raw_event_id"]

        def event() -> RawEvent:
            found = queue.get(event_id)
            assert found is not None
            return found

        wait_until(lambda: event().status == EventStatus.DEAD)
        first = event()
        replay = client.post(f"/admin/raw-events/{event_id}/replay", headers={"X-API-Key": KEY_A})
        assert replay.json() == {"status": "pending"}
        wait_until(
            lambda: (
                event().status == EventStatus.DEAD
                and event().next_attempt_at > first.next_attempt_at
            )
        )
        assert event().attempts == 1
        assert event().error == first.error
