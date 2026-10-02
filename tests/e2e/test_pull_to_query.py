from dataclasses import replace

from discourse_mock import discourse_http
from fastapi.testclient import TestClient
from helpers import KEY_A, add_pull_source, seed_source, wait_until

from feedback_ingest.config import Settings
from feedback_ingest.domain.enums import EventStatus, FeedbackKind
from feedback_ingest.domain.metadata import DiscourseMetadata
from feedback_ingest.main import create_app
from feedback_ingest.wiring import sql_adapters


def test_sync_pulls_posts_and_a_second_sync_only_finds_duplicates(settings: Settings) -> None:
    headers = {"X-API-Key": KEY_A}
    with sql_adapters(settings) as built:
        adapters = replace(built, http=discourse_http())
        seed_source(adapters, "tenant-a", KEY_A)
        forum = add_pull_source(adapters, "src-forum")
        with TestClient(create_app(settings, adapters=adapters)) as client:
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
