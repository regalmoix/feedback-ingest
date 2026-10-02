from datetime import datetime

import pytest
from connector_fixtures import load, source
from pydantic import ValidationError

from feedback_ingest.connectors.discourse import DiscourseConnector
from feedback_ingest.domain.enums import FeedbackKind, SourceType
from feedback_ingest.domain.errors import TransformError
from feedback_ingest.domain.metadata import DiscourseMetadata

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
        topic_title="Dark mode export button",
        url="https://forum.example.test/t/dark-mode-export-button/512/3",
    )
    assert DISCOURSE.external_event_id(payload) == "9001:2026-02-10T09:15:00"


def test_deleted_post_is_a_tombstone() -> None:
    [record] = DISCOURSE.transform(SOURCE, load(SourceType.DISCOURSE, "post_deleted"))
    deleted = datetime(2026, 2, 12, 10, 0)  # noqa: DTZ001  naive UTC is the storage convention
    assert record.deleted_at == deleted
    assert record.author == "sample_poster"


def test_missing_base_url_is_a_transform_error() -> None:
    no_config = SOURCE.model_copy(update={"config": {}})
    with pytest.raises(TransformError, match="base_url"):
        DISCOURSE.transform(no_config, load(SourceType.DISCOURSE, "post"))


def test_post_with_bad_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="id"):
        DISCOURSE.transform(SOURCE, load(SourceType.DISCOURSE, "malformed"))
