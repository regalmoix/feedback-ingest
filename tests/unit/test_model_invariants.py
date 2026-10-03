from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from feedback_ingest.connectors.base import RecordContent, new_record
from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.enums import EventStatus, SourceType
from feedback_ingest.domain.metadata import (
    CustomMetadata,
    DiscourseMetadata,
    IntercomMetadata,
    TwitterMetadata,
)
from feedback_ingest.domain.models import FeedbackRecord, RawEvent, Source, Tenant
from feedback_ingest.services.pull import PullResult

NOW = datetime(2026, 3, 1, 12, 0)
SOURCE = Source(
    id="s1", tenant_id="t1", type="twitter", name="x", mode="pull", config={}, cursor=None
)
CONTENT: RecordContent = {
    "title": None,
    "text": "hi",
    "author": None,
    "language": None,
    "rating": None,
    "source_created_at": NOW,
    "source_updated_at": None,
    "deleted_at": None,
    "metadata": TwitterMetadata(country=None, retweets=0),
}
EVENT: dict[str, Any] = {
    "id": "e1",
    "tenant_id": "t1",
    "source_id": "s1",
    "external_event_id": "x1",
    "payload": {},
    "received_at": NOW,
    "next_attempt_at": NOW,
}


def test_content_cannot_override_the_records_identity() -> None:
    twitter = CONNECTORS[SourceType.TWITTER]
    record = new_record(SOURCE, twitter, "x1", **CONTENT, tenant_id="t2")  # type: ignore[call-arg]
    assert (record.tenant_id, record.source_id, record.external_id) == ("t1", "s1", "x1")


def test_new_record_fills_kind_from_the_source_type_and_a_wrong_kind_is_refused() -> None:
    record = new_record(SOURCE, CONNECTORS[SourceType.TWITTER], "x1", **CONTENT)
    assert record.model_dump()["kind"] == "post"
    with pytest.raises(ValidationError, match="a twitter record is a post, not review"):
        FeedbackRecord.model_validate(record.model_dump() | {"kind": "review"})


def test_a_custom_records_kind_must_match_its_record_type() -> None:
    record = new_record(SOURCE, CONNECTORS[SourceType.TWITTER], "x1", **CONTENT)
    custom = {"source_type": "custom", "metadata": CustomMetadata(record_type="REVIEW")}
    assert FeedbackRecord.model_validate(record.model_dump() | custom | {"kind": "review"})
    with pytest.raises(ValidationError, match="a custom record is a review, not survey"):
        FeedbackRecord.model_validate(record.model_dump() | custom | {"kind": "survey"})


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
def test_names_are_trimmed_non_empty_and_bounded(name: str) -> None:
    with pytest.raises(ValidationError):
        Tenant(id="t1", name=name, api_key_hash="h")
    with pytest.raises(ValidationError):
        SOURCE.model_validate(SOURCE.model_dump() | {"name": name})
    assert Tenant(id="t1", name="  acme ", api_key_hash="h").name == "acme"


@pytest.mark.parametrize(
    "build",
    [
        lambda: DiscourseMetadata(topic_id=0, post_number=1, like_count=0, url="u"),
        lambda: DiscourseMetadata(topic_id=1, post_number=0, like_count=0, url="u"),
        lambda: DiscourseMetadata(topic_id=1, post_number=1, like_count=-1, url="u"),
        lambda: TwitterMetadata(country=None, retweets=-1),
        lambda: IntercomMetadata(part_count=-1, tags=()),
        lambda: PullResult(source_id="s1", pages=-1),
    ],
)
def test_counters_and_ids_reject_impossible_values(build: Any) -> None:  # noqa: ANN401
    with pytest.raises(ValidationError):
        build()


def test_pull_result_is_frozen() -> None:
    with pytest.raises(ValidationError):
        PullResult(source_id="s1").pages = 3  # type: ignore[misc]


@pytest.mark.parametrize(
    ("status", "lease_until"),
    [(EventStatus.PROCESSING, None), (EventStatus.PENDING, NOW), (EventStatus.DEAD, NOW)],
)
def test_a_lease_exists_exactly_while_processing(
    status: EventStatus, lease_until: datetime | None
) -> None:
    with pytest.raises(ValidationError, match="lease_until"):
        RawEvent.model_validate(EVENT | {"status": status, "lease_until": lease_until})
    assert RawEvent.model_validate(EVENT | {"status": EventStatus.PROCESSING, "lease_until": NOW})
