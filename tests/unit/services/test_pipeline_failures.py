import json
from datetime import timedelta

import pytest
from api.conftest import KEY_A, fixture_body, memory_adapters, seed_source

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.api.deps import Adapters
from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.enums import EventStatus, SourceType
from feedback_ingest.domain.errors import TransformError, TransientError
from feedback_ingest.domain.models import FeedbackRecord, RawEvent
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.services.pipeline import PipelineService

LEASE = 30


@pytest.fixture
def adapters(clock: FixedClock) -> Adapters:
    return memory_adapters(clock)


def _pipeline(a: Adapters, backoff_cap_seconds: int = 300) -> PipelineService:
    return PipelineService(a.sources, a.feedback, a.queue, a.clock, 5, backoff_cap_seconds)


def _claimed(adapters: Adapters, fixture: str) -> RawEvent:
    source = seed_source(adapters, "tenant-a", KEY_A)
    body = json.loads(fixture_body(SourceType.PLAYSTORE, fixture))
    IngestionService(adapters.queue, adapters.clock).accept(source, body)
    [event] = adapters.queue.claim(adapters.clock.now(), LEASE, 1)
    return event


def _fail_with(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    def failing(*_args: object) -> list[FeedbackRecord]:
        raise exc

    monkeypatch.setattr(CONNECTORS[SourceType.PLAYSTORE], "transform", failing)


@pytest.mark.parametrize(
    ("fixture", "error"),
    [("review", None), ("malformed", None), ("review", TransientError("upstream timeout"))],
    ids=["mark_processed", "mark_dead", "mark_failed"],
)
def test_a_stale_copy_after_a_reclaim_leaves_the_row_with_the_newer_claim(
    adapters: Adapters,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    fixture: str,
    error: Exception | None,
) -> None:
    stale = _claimed(adapters, fixture)
    assert isinstance(adapters.clock, FixedClock)
    adapters.clock.advance(LEASE + 1)
    [newer] = adapters.queue.claim(adapters.clock.now(), LEASE, 1)
    if error is not None:
        _fail_with(monkeypatch, error)
    assert _pipeline(adapters).process(stale) == EventStatus.PROCESSING
    assert adapters.queue.get(stale.id) == newer
    assert "lease lost" in caplog.text
    assert "processed into" not in caplog.text


def test_backoff_is_capped(
    adapters: Adapters, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_with(monkeypatch, TransientError("upstream timeout"))
    event = _claimed(adapters, "review")
    assert event.attempts == 1
    assert _pipeline(adapters, backoff_cap_seconds=1).process(event) == EventStatus.FAILED
    stored = adapters.queue.get(event.id)
    assert stored is not None
    assert stored.next_attempt_at == clock.now() + timedelta(seconds=1)


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (TransientError("x" * 600), EventStatus.FAILED),
        (TransformError("x" * 600), EventStatus.DEAD),
    ],
)
def test_error_text_is_truncated_to_500_chars(
    adapters: Adapters, monkeypatch: pytest.MonkeyPatch, exc: Exception, status: EventStatus
) -> None:
    _fail_with(monkeypatch, exc)
    event = _claimed(adapters, "review")
    assert _pipeline(adapters).process(event) == status
    stored = adapters.queue.get(event.id)
    assert stored is not None
    assert stored.error is not None
    assert len(stored.error) == 500


def test_event_past_the_attempt_cap_is_dead_without_transforming(
    adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_with(monkeypatch, AssertionError("connector must not run"))
    claimed = _claimed(adapters, "review")
    for _ in range(5):  # crashes outside the handler: lease expires, claim bumps attempts
        assert isinstance(adapters.clock, FixedClock)
        adapters.clock.advance(LEASE + 1)
        [claimed] = adapters.queue.claim(adapters.clock.now(), LEASE, 1)
    assert claimed.attempts == 6
    assert _pipeline(adapters).process(claimed) == EventStatus.DEAD
    stored = adapters.queue.get(claimed.id)
    assert stored is not None
    assert (stored.status, stored.error) == (EventStatus.DEAD, "attempt limit exceeded")
