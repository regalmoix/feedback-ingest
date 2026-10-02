from datetime import datetime

import pytest
from connector_fixtures import load, source
from pydantic import ValidationError

from feedback_ingest.connectors.intercom import IntercomConnector
from feedback_ingest.domain.enums import FeedbackKind, SourceType
from feedback_ingest.domain.metadata import IntercomMetadata

INTERCOM = IntercomConnector()
SOURCE = source(SourceType.INTERCOM)


def test_conversation_parts_are_joined_in_time_order() -> None:
    payload = load(SourceType.INTERCOM, "conversation_updated")
    [record] = INTERCOM.transform(SOURCE, payload)
    assert record.kind is FeedbackKind.CONVERSATION
    assert record.external_id == "conv_test_1001"
    assert record.title == "Billing page shows wrong currency"
    assert record.author == "Riley Placeholder"
    assert record.text == (
        "The billing page shows USD but my account is in EUR."
        "\n\nFixed — please refresh.\n\nThanks, it shows EUR now."
    )
    created = datetime(2026, 2, 13, 16, 26, 40)  # noqa: DTZ001  naive UTC is the storage convention
    updated = datetime(2026, 2, 13, 17, 26, 40)  # noqa: DTZ001  naive UTC is the storage convention
    assert (record.source_created_at, record.source_updated_at) == (created, updated)
    assert record.metadata == IntercomMetadata(
        conversation_id="conv_test_1001", part_count=3, tags=("billing", "resolved"), state="closed"
    )
    assert INTERCOM.external_event_id(payload) == "conv_test_1001:1771003600"


def test_non_conversation_topic_is_not_feedback() -> None:
    assert INTERCOM.transform(SOURCE, load(SourceType.INTERCOM, "ping")) == []


def test_conversation_missing_fields_is_rejected() -> None:
    with pytest.raises(ValidationError, match="source"):
        INTERCOM.transform(SOURCE, load(SourceType.INTERCOM, "malformed"))
