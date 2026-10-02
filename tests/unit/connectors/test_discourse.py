from datetime import datetime

from connector_fixtures import load, source

from feedback_ingest.connectors.discourse import DiscourseConnector
from feedback_ingest.domain.enums import FeedbackKind, SourceType
from feedback_ingest.domain.metadata import DiscourseMetadata
from feedback_ingest.utils.hashing import payload_hash

DISCOURSE = DiscourseConnector()
SOURCE = source(SourceType.DISCOURSE)


def test_post_maps_to_a_record() -> None:
    payload = load(SourceType.DISCOURSE, "post")
    [record] = DISCOURSE.transform(SOURCE, payload)
    assert record.kind is FeedbackKind.POST
    assert record.external_id == "9001"
    assert record.text == (
        "Dark mode makes the export button invisible. Steps: open settings & switch theme."
    )
    assert (record.title, record.author) == ("Dark mode export button", "Avery Example")
    assert (record.language, record.rating, record.deleted_at) == (None, None, None)
    assert record.metadata == DiscourseMetadata(
        topic_id=512,
        post_number=3,
        like_count=4,
        url="https://forum.example.test/t/dark-mode-export-button/512/3",
    )
    assert DISCOURSE.external_event_id(payload) == "9001:2026-02-10T09:15:00"


def test_deleted_post_is_a_tombstone_and_a_new_event_without_an_updated_at_bump() -> None:
    deleted = load(SourceType.DISCOURSE, "post_deleted")
    [record] = DISCOURSE.transform(SOURCE, deleted)
    assert record.deleted_at == datetime(2026, 2, 12, 10, 0)
    assert record.author == "sample_poster"
    assert DISCOURSE.external_event_id(deleted) == "9002:2026-02-12T10:00:00"
    assert DISCOURSE.external_event_id(deleted | {"deleted_at": None}) == "9002:2026-02-12T08:00:00"


def test_event_id_falls_back_to_created_at_without_updated_at() -> None:
    payload = load(SourceType.DISCOURSE, "post")
    del payload["updated_at"]
    assert DISCOURSE.external_event_id(payload) == "9001:2026-02-10T09:15:00"


def test_out_of_range_timestamp_falls_back_to_the_payload_hash() -> None:
    payload = load(SourceType.DISCOURSE, "post") | {"created_at": "0001-01-01T00:00:00+01:00"}
    del payload["updated_at"]
    assert DISCOURSE.external_event_id(payload) == payload_hash(payload)
