from api.conftest import KEY_A, seed_source
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from e2e.conftest import add_pull_source, discourse_http, wait_until
from feedback_ingest.adapters.sqlalchemy.raw_event_queue import SqlRawEventQueue
from feedback_ingest.adapters.sqlalchemy.stores import (
    SqlFeedbackStore,
    SqlSourceStore,
    SqlTenantStore,
)
from feedback_ingest.api.deps import Adapters
from feedback_ingest.config import Settings
from feedback_ingest.domain.enums import EventStatus, FeedbackKind
from feedback_ingest.domain.metadata import DiscourseMetadata
from feedback_ingest.main import create_app
from feedback_ingest.utils.time import SystemClock


def test_sync_pulls_posts_and_a_second_sync_only_finds_duplicates(
    settings: Settings, engine: Engine
) -> None:
    adapters = Adapters(
        tenants=SqlTenantStore(engine),
        sources=SqlSourceStore(engine),
        feedback=SqlFeedbackStore(engine),
        queue=SqlRawEventQueue(engine),
        http=discourse_http(),
        clock=SystemClock(),
    )
    seed_source(adapters, "tenant-a", KEY_A)
    forum = add_pull_source(adapters, "src-forum")
    app = create_app(settings.model_copy(update={"scheduler_enabled": False}), adapters=adapters)
    headers = {"X-API-Key": KEY_A}
    with TestClient(app) as client:
        first = client.post(f"/v1/sources/{forum.id}/sync", headers=headers).json()
        assert (first["pages"], first["accepted"], first["error"]) == (2, 4, None)
        wait_until(lambda: adapters.queue.counts()[EventStatus.PROCESSED] == 4)
        second = client.post(f"/v1/sources/{forum.id}/sync", headers=headers).json()
        assert (second["accepted"], second["duplicates"]) == (0, 4)
        records = adapters.feedback.list_for_tenant("tenant-a", source_id=forum.id)
    assert sum(adapters.queue.counts().values()) == 4
    assert {r.kind for r in records} == {FeedbackKind.POST}
    assert sorted(r.external_id for r in records) == ["9101", "9102", "9201", "9202"]
    topics = {r.metadata.topic_id for r in records if isinstance(r.metadata, DiscourseMetadata)}
    assert topics == {601, 602}
    assert {r.title for r in records} == {
        "Export to CSV drops the last row",
        "Sidebar flickers on resize",
    }
