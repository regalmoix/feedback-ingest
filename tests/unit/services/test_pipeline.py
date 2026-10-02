import json
from datetime import timedelta

import pytest
from api.conftest import KEY_A, fixture_body, memory_adapters, seed_source

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.api.deps import Adapters
from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.enums import EventStatus, SourceType
from feedback_ingest.domain.errors import TransientError
from feedback_ingest.domain.models import FeedbackRecord, RawEvent, Source
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.services.pipeline import PipelineService

MAX_ATTEMPTS = 3


@pytest.fixture
def adapters(clock: FixedClock) -> Adapters:
    return memory_adapters(clock)


@pytest.fixture
def pipeline(adapters: Adapters) -> PipelineService:
    a = adapters
    return PipelineService(a.sources, a.feedback, a.queue, a.clock, MAX_ATTEMPTS, 300)


def _claimed(adapters: Adapters, source: Source, body: bytes) -> RawEvent:
    IngestionService(adapters.queue, adapters.clock).accept(source, json.loads(body))
    [event] = adapters.queue.claim(adapters.clock.now(), 30, 1)
    return event


def _stored(adapters: Adapters, event: RawEvent) -> RawEvent:
    stored = adapters.queue.get(event.id)
    assert stored is not None
    return stored


def test_happy_path_upserts_records_stamped_with_the_clock(
    adapters: Adapters, pipeline: PipelineService
) -> None:
    source = seed_source(adapters, "tenant-a", KEY_A)
    event = _claimed(adapters, source, fixture_body(SourceType.PLAYSTORE, "review"))
    assert pipeline.process(event) == EventStatus.PROCESSED
    assert _stored(adapters, event).status == EventStatus.PROCESSED
    [record] = adapters.feedback.list_for_tenant(source.tenant_id)
    assert record.ingested_at == adapters.clock.now()
    assert record.external_id == "gp:AOqpTEST-review-0001"


def test_malformed_payload_is_dead_on_the_first_attempt(
    adapters: Adapters, pipeline: PipelineService
) -> None:
    source = seed_source(adapters, "tenant-a", KEY_A)
    event = _claimed(adapters, source, fixture_body(SourceType.PLAYSTORE, "malformed"))
    assert pipeline.process(event) == EventStatus.DEAD
    stored = _stored(adapters, event)
    assert stored.attempts == 1
    assert stored.error
    assert "comments" in stored.error


@pytest.mark.parametrize("error", [TransientError, RuntimeError])
def test_failures_back_off_exponentially_then_go_dead(
    adapters: Adapters,
    clock: FixedClock,
    pipeline: PipelineService,
    monkeypatch: pytest.MonkeyPatch,
    error: type[Exception],
) -> None:
    def failing(*_args: object) -> list[FeedbackRecord]:
        msg = "upstream timeout"
        raise error(msg)

    monkeypatch.setattr(CONNECTORS[SourceType.PLAYSTORE], "transform", failing)
    source = seed_source(adapters, "tenant-a", KEY_A)
    event = _claimed(adapters, source, fixture_body(SourceType.PLAYSTORE, "review"))
    for attempt in range(1, MAX_ATTEMPTS):
        assert event.attempts == attempt
        assert pipeline.process(event) == EventStatus.FAILED
        stored = _stored(adapters, event)
        assert stored.next_attempt_at == clock.now() + timedelta(seconds=2**attempt)
        clock.advance(2**attempt)
        [event] = adapters.queue.claim(clock.now(), 30, 1)
    assert pipeline.process(event) == EventStatus.DEAD
    assert _stored(adapters, event).error == f"{error.__name__}: upstream timeout"


def test_unknown_source_is_dead(adapters: Adapters, pipeline: PipelineService) -> None:
    source = seed_source(adapters, "tenant-a", KEY_A).model_copy(update={"id": "ghost"})
    event = _claimed(adapters, source, fixture_body(SourceType.PLAYSTORE, "review"))
    assert pipeline.process(event) == EventStatus.DEAD
    assert _stored(adapters, event).error == "source not found"


def test_tombstone_record_flows_through(adapters: Adapters, pipeline: PipelineService) -> None:
    source = seed_source(adapters, "tenant-a", KEY_A, SourceType.DISCOURSE)
    event = _claimed(adapters, source, fixture_body(SourceType.DISCOURSE, "post_deleted"))
    assert pipeline.process(event) == EventStatus.PROCESSED
    assert adapters.feedback.list_for_tenant(source.tenant_id) == []
    [record] = adapters.feedback.list_for_tenant(source.tenant_id, include_deleted=True)
    assert record.deleted_at is not None
