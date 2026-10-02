import copy
from datetime import datetime

import pytest
from connector_fixtures import load, source

from feedback_ingest.connectors.intercom import IntercomConnector
from feedback_ingest.domain.enums import FeedbackKind, SourceType
from feedback_ingest.domain.errors import TransformError
from feedback_ingest.domain.metadata import IntercomMetadata
from feedback_ingest.utils.hashing import payload_hash

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
    created, updated = datetime(2026, 2, 13, 16, 26, 40), datetime(2026, 2, 13, 17, 26, 40)
    assert (record.source_created_at, record.source_updated_at) == (created, updated)
    assert record.metadata == IntercomMetadata(
        part_count=3, tags=("billing", "resolved"), state="closed"
    )
    item_hash = payload_hash(payload["data"]["item"])[:12]
    assert INTERCOM.external_event_id(payload) == f"conv_test_1001:2026-02-13T17:26:40:{item_hash}"


def test_two_snapshots_in_the_same_second_are_two_events() -> None:
    payload = load(SourceType.INTERCOM, "conversation_updated")
    later = copy.deepcopy(payload)
    later["data"]["item"]["state"] = "snoozed"
    assert INTERCOM.external_event_id(payload) != INTERCOM.external_event_id(later)


def test_source_body_and_part_ids_are_optional() -> None:
    payload = load(SourceType.INTERCOM, "conversation_updated")
    item = payload["data"]["item"]
    item["source"]["body"] = None
    for part in item["conversation_parts"]["conversation_parts"]:
        del part["id"], part["author"]
    [record] = INTERCOM.transform(SOURCE, payload)
    assert record.text == "Fixed — please refresh.\n\nThanks, it shows EUR now."


def test_ping_is_not_feedback_and_unknown_topics_go_dead() -> None:
    ping = load(SourceType.INTERCOM, "ping")
    assert INTERCOM.transform(SOURCE, ping) == []
    with pytest.raises(TransformError, match=r"unsupported topic conversation_part\.redacted"):
        INTERCOM.transform(SOURCE, ping | {"topic": "conversation_part.redacted"})
