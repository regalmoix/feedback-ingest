from datetime import UTC, datetime, timedelta, timezone
from typing import Any, get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from feedback_ingest.domain.enums import SourceType
from feedback_ingest.domain.metadata import IntercomMetadata, SourceMetadata, TwitterMetadata
from feedback_ingest.domain.models import FeedbackRecord, RawEvent, Source

_METADATA: TypeAdapter[SourceMetadata] = TypeAdapter(SourceMetadata)
_NOW = datetime(2026, 1, 1, 12, 0)
_RECORD: dict[str, Any] = {
    "id": "r1",
    "tenant_id": "t1",
    "source_id": "s1",
    "source_type": "twitter",
    "external_id": "x1",
    "title": None,
    "text": "hi",
    "author": None,
    "language": None,
    "rating": None,
    "source_created_at": _NOW,
    "source_updated_at": None,
    "ingested_at": _NOW,
    "deleted_at": None,
    "connector_version": 1,
    "metadata": {"source_type": "twitter", "country": None, "retweets": 0},
}
_SOURCE: dict[str, Any] = {
    "id": "s1",
    "tenant_id": "t1",
    "type": "playstore",
    "name": "app",
    "mode": "push",
    "config": {},
    "cursor": None,
}


def test_aware_datetimes_become_naive_utc() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    event = RawEvent(
        id="e1",
        tenant_id="t1",
        source_id="s1",
        external_event_id="x1",
        payload={},
        received_at=datetime(2026, 1, 1, 17, 30, tzinfo=ist),
        next_attempt_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert (event.received_at, event.next_attempt_at) == (_NOW, _NOW)


def test_metadata_round_trips_through_json() -> None:
    metadata = IntercomMetadata(part_count=2, tags=("bug", "ui"))
    assert _METADATA.validate_json(_METADATA.dump_json(metadata)) == metadata


def test_every_source_type_has_a_metadata_model() -> None:
    models = get_args(get_args(SourceMetadata)[0])
    literals = {get_args(m.model_fields["source_type"].annotation)[0] for m in models}
    assert literals == set(SourceType)


def test_metadata_ignores_unknown_keys_and_rejects_unknown_source() -> None:
    stored = {"source_type": "twitter", "country": None, "retweets": 1, "new": 1}
    assert _METADATA.validate_python(stored) == TwitterMetadata(country=None, retweets=1)
    with pytest.raises(ValidationError):
        _METADATA.validate_python({"source_type": "myspace"})


@pytest.mark.parametrize(
    "bad",
    [
        {"source_type": "discourse"},
        {"rating": 0},
        {"rating": 6},
        {"connector_version": 0},
    ],
)
def test_record_rejects_inconsistent_or_out_of_range_fields(bad: dict[str, Any]) -> None:
    assert FeedbackRecord.model_validate(_RECORD | {"kind": "review"}).kind == "post"
    with pytest.raises(ValidationError):
        FeedbackRecord.model_validate(_RECORD | bad)


def test_raw_event_attempts_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        RawEvent(
            id="e1",
            tenant_id="t1",
            source_id="s1",
            external_event_id="x1",
            payload={},
            received_at=_NOW,
            next_attempt_at=_NOW,
            attempts=-1,
        )


@pytest.mark.parametrize("secret", [None, ""])
def test_push_source_needs_a_secret(secret: str | None) -> None:
    with pytest.raises(ValidationError):
        Source.model_validate(_SOURCE | {"webhook_secret": secret})
    assert Source.model_validate(_SOURCE | {"mode": "pull", "webhook_secret": secret})


def test_webhook_secret_is_hidden_from_repr_and_dump() -> None:
    source = Source.model_validate(_SOURCE | {"webhook_secret": "hunter2"})
    assert "hunter2" not in repr(source)
    assert "hunter2" not in str(source.model_dump(mode="json"))
