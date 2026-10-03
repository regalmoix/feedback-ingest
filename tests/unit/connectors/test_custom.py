from datetime import datetime
from typing import get_args

import pytest
from connector_fixtures import source
from helpers import load
from pydantic import ValidationError

from feedback_ingest.connectors.custom import CustomConnector
from feedback_ingest.domain.enums import (
    KIND_BY_RECORD_TYPE,
    CustomRecordType,
    FeedbackKind,
    SourceType,
)
from feedback_ingest.domain.errors import PermanentError
from feedback_ingest.domain.metadata import CustomMetadata
from feedback_ingest.utils.hashing import payload_hash

CUSTOM = CustomConnector()
SOURCE = source(SourceType.CUSTOM)


def test_a_batch_gives_one_record_per_entry_with_the_kind_from_its_type() -> None:
    payload = load(SourceType.CUSTOM, "batch")
    review, chat, survey = CUSTOM.transform(SOURCE, payload)
    assert [r.kind for r in (review, chat, survey)] == [
        FeedbackKind.REVIEW,
        FeedbackKind.CONVERSATION,
        FeedbackKind.SURVEY,
    ]
    assert [r.external_id for r in (review, chat, survey)] == [
        "lumenote-review-0001",
        "lumenote-chat-0001",
        "lumenote-nps-0001",
    ]
    assert (review.rating, review.language, review.author) == (2, "en", "Avery Sample")
    assert review.source_created_at == datetime(2026, 2, 3, 6, 26, 40)
    assert review.source_updated_at is None
    assert chat.title == "Export to PDF missing"
    assert survey.metadata == CustomMetadata(
        record_type="SURVEY", score=8, fields={"survey": "nps-2026-q1", "paying": True}
    )
    assert CUSTOM.external_event_id(payload) == payload_hash(payload)


def test_forum_threads_are_posts_and_millisecond_epochs_are_accepted() -> None:
    payload = load(SourceType.CUSTOM, "batch")
    payload["records"] = [
        payload["records"][0] | {"type": "FORUM_CONVERSATION_THREAD", "createdAt": 1770100000000}
    ]
    [record] = CUSTOM.transform(SOURCE, payload)
    assert record.kind is FeedbackKind.POST
    assert record.source_created_at == datetime(2026, 2, 3, 6, 26, 40)


def test_metadata_keeps_its_value_types_and_rejects_nesting() -> None:
    *_, survey = CUSTOM.transform(SOURCE, load(SourceType.CUSTOM, "batch"))
    assert isinstance(survey.metadata, CustomMetadata)
    assert survey.metadata.fields["paying"] is True
    assert isinstance(survey.metadata.score, float)
    with pytest.raises(ValidationError, match=r"metadata\.rating"):
        CUSTOM.transform(SOURCE, load(SourceType.CUSTOM, "malformed"))


def test_an_unsupported_type_or_an_empty_batch_goes_dead() -> None:
    with pytest.raises(PermanentError, match="unsupported record type AUDIO_RECORDING"):
        CUSTOM.transform(SOURCE, load(SourceType.CUSTOM, "unsupported_type"))
    with pytest.raises(ValidationError):
        CUSTOM.transform(SOURCE, {"records": []})


def test_every_record_type_has_a_kind() -> None:
    assert set(get_args(CustomRecordType)) == KIND_BY_RECORD_TYPE.keys()
