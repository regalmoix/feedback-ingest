from datetime import timedelta

import pytest
from helpers import KEY_A, load, seed_source

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.api.deps import Adapters
from feedback_ingest.connectors.playstore import PlaystoreConnector
from feedback_ingest.domain.enums import EventStatus, SourceType
from feedback_ingest.domain.errors import TransientError
from feedback_ingest.domain.models import FeedbackRecord, RawEvent, Source
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.services.pipeline import PipelineService

MAX_ATTEMPTS, LEASE = 3, 30


def make_pipeline(a: Adapters, backoff_cap_seconds: int = 300) -> PipelineService:
    return PipelineService(
        a.sources, a.feedback, a.queue, a.clock, MAX_ATTEMPTS, backoff_cap_seconds
    )


def claimed(adapters: Adapters, fixture: str = "review", source: Source | None = None) -> RawEvent:
    source = source or seed_source(adapters, "tenant-a", KEY_A)
    body = load(source.type, fixture)
    IngestionService(adapters.queue, adapters.clock).accept(source, body)
    [event] = adapters.queue.claim(adapters.clock.now(), LEASE, 1)
    return event


def fail_with(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    def failing(*_args: object) -> list[FeedbackRecord]:
        raise exc

    monkeypatch.setattr(PlaystoreConnector, "transform", failing)


def stored(adapters: Adapters, event: RawEvent) -> RawEvent:
    found = adapters.queue.get(event.id)
    assert found is not None
    return found


def test_happy_path_upserts_records_stamped_with_the_clock(
    adapters: Adapters, caplog: pytest.LogCaptureFixture
) -> None:
    event = claimed(adapters)
    assert make_pipeline(adapters).process(event) == EventStatus.PROCESSED
    assert stored(adapters, event).status == EventStatus.PROCESSED
    [record] = adapters.feedback.list_for_tenant("tenant-a")
    assert record.ingested_at == adapters.clock.now()
    assert record.external_id == "gp:AOqpTEST-review-0001"
    assert "processed: inserted=1, updated=0, skipped_older=0" in caplog.text


def test_malformed_payload_is_dead_on_the_first_attempt_without_customer_text(
    adapters: Adapters, caplog: pytest.LogCaptureFixture
) -> None:
    event = claimed(adapters, "malformed")
    assert make_pipeline(adapters).process(event) == EventStatus.DEAD
    dead = stored(adapters, event)
    assert dead.attempts == 1
    assert dead.error
    assert "comments" in dead.error
    text = "no rating and no timestamp"  # the payload's review text
    assert text not in dead.error
    assert text not in caplog.text


@pytest.mark.parametrize(
    "case",
    [
        (TransientError, "TransientError: upstream timeout"),
        (RuntimeError, "RuntimeError (see logs)"),  # unknown text may hold customer data
    ],
)
def test_failures_back_off_exponentially_then_go_dead(
    adapters: Adapters,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    case: tuple[type[Exception], str],
) -> None:
    error, stored_error = case
    fail_with(monkeypatch, error("upstream timeout"))
    event, pipeline = claimed(adapters), make_pipeline(adapters)
    for attempt in range(1, MAX_ATTEMPTS):
        assert event.attempts == attempt
        assert pipeline.process(event) == EventStatus.FAILED
        assert stored(adapters, event).next_attempt_at == clock.now() + timedelta(
            seconds=2**attempt
        )
        clock.advance(2**attempt)
        [event] = adapters.queue.claim(clock.now(), LEASE, 1)
    assert pipeline.process(event) == EventStatus.DEAD
    assert stored(adapters, event).error == stored_error
    assert f"dead: {stored_error}" in caplog.text


def test_unknown_source_is_dead(adapters: Adapters) -> None:
    ghost = seed_source(adapters, "tenant-a", KEY_A).model_copy(update={"id": "ghost"})
    event = claimed(adapters, source=ghost)
    assert make_pipeline(adapters).process(event) == EventStatus.DEAD
    assert stored(adapters, event).error == "source not found"


def test_tombstone_record_flows_through(adapters: Adapters) -> None:
    forum = seed_source(adapters, "tenant-a", KEY_A, SourceType.DISCOURSE)
    event = claimed(adapters, "post_deleted", forum)
    assert make_pipeline(adapters).process(event) == EventStatus.PROCESSED
    assert adapters.feedback.list_for_tenant("tenant-a") == []
    [record] = adapters.feedback.list_for_tenant("tenant-a", include_deleted=True)
    assert record.deleted_at is not None
