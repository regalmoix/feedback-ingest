from datetime import datetime

import pytest
from connector_fixtures import load, source
from pydantic import ValidationError

from feedback_ingest.connectors.playstore import PlaystoreConnector
from feedback_ingest.domain.enums import FeedbackKind, SourceType
from feedback_ingest.domain.metadata import PlaystoreMetadata

PLAYSTORE = PlaystoreConnector()
SOURCE = source(SourceType.PLAYSTORE)


def test_review_maps_to_a_record() -> None:
    payload = load(SourceType.PLAYSTORE, "review")
    [record] = PLAYSTORE.transform(SOURCE, payload)
    modified = datetime(2026, 2, 2, 2, 40)  # noqa: DTZ001  naive UTC is the storage convention
    assert record.kind is FeedbackKind.REVIEW
    assert record.external_id == "gp:AOqpTEST-review-0001"
    assert record.text == "App crashes when I rotate the phone on the checkout screen."
    assert (record.rating, record.language, record.author) == (2, "en", "Jordan Sample")
    assert record.title is None
    assert record.source_created_at == record.source_updated_at == modified
    assert record.metadata == PlaystoreMetadata(
        app_version="4.2.1", device="testdevice_a1", android_os_version=34
    )
    assert PLAYSTORE.external_event_id(payload) == "gp:AOqpTEST-review-0001:1770000000"


def test_developer_reply_is_ignored() -> None:
    [record] = PLAYSTORE.transform(SOURCE, load(SourceType.PLAYSTORE, "review_edited"))
    assert record.text.startswith("Fixed in 4.2.2")
    assert record.rating == 4


def test_review_without_user_comment_is_rejected() -> None:
    with pytest.raises(ValidationError, match="comments"):
        PLAYSTORE.transform(SOURCE, load(SourceType.PLAYSTORE, "malformed"))
