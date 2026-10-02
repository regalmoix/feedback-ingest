from datetime import timedelta

import pytest
from pydantic import BaseModel, ValidationError
from test_pipeline import LEASE, MAX_ATTEMPTS, claimed, fail_with, make_pipeline, stored

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.enums import EventStatus
from feedback_ingest.domain.errors import TransformError, TransientError


@pytest.mark.parametrize(
    "case",
    [("review", None), ("malformed", None), ("review", TransientError("upstream timeout"))],
    ids=["mark_processed", "mark_dead", "mark_failed"],
)
def test_a_stale_copy_after_a_reclaim_leaves_the_row_with_the_newer_claim(
    adapters: Adapters,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    case: tuple[str, Exception | None],
) -> None:
    fixture, error = case
    stale = claimed(adapters, fixture)
    clock.advance(LEASE + 1)
    [newer] = adapters.queue.claim(adapters.clock.now(), LEASE, 1)
    if error is not None:
        fail_with(monkeypatch, error)
    assert make_pipeline(adapters).process(stale) == EventStatus.PROCESSING
    assert adapters.queue.get(stale.id) == newer
    assert "lease lost" in caplog.text
    assert "inserted=" not in caplog.text


def test_backoff_is_capped(
    adapters: Adapters, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    fail_with(monkeypatch, TransientError("upstream timeout"))
    event = claimed(adapters)
    assert event.attempts == 1
    assert make_pipeline(adapters, backoff_cap_seconds=1).process(event) == EventStatus.FAILED
    assert stored(adapters, event).next_attempt_at == clock.now() + timedelta(seconds=1)


class _Ints(BaseModel):
    values: list[int]


def _fifty_part_validation_error() -> ValidationError:
    try:
        _Ints.model_validate({"values": ["x"] * 50})
    except ValidationError as exc:
        return exc
    raise AssertionError


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (TransientError("x" * 600), EventStatus.FAILED),
        (TransformError("x" * 600), EventStatus.DEAD),
        (_fifty_part_validation_error(), EventStatus.DEAD),
    ],
)
def test_error_text_is_truncated_to_500_chars(
    adapters: Adapters, monkeypatch: pytest.MonkeyPatch, exc: Exception, status: EventStatus
) -> None:
    fail_with(monkeypatch, exc)
    event = claimed(adapters)
    assert make_pipeline(adapters).process(event) == status
    error = stored(adapters, event).error
    assert error is not None
    assert len(error) == 500


def test_event_past_the_attempt_cap_is_dead_without_transforming(
    adapters: Adapters, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline = make_pipeline(adapters)
    fail_with(monkeypatch, TransientError("upstream timeout"))
    event = claimed(adapters)
    assert pipeline.process(event) == EventStatus.FAILED  # leaves an error behind
    fail_with(monkeypatch, AssertionError("connector must not run"))
    for _ in range(MAX_ATTEMPTS):  # crashes outside the handler: the lease expires, attempts grow
        clock.advance(300)
        [event] = adapters.queue.claim(clock.now(), LEASE, 1)
    assert event.attempts == MAX_ATTEMPTS + 1
    assert pipeline.process(event) == EventStatus.DEAD
    dead = stored(adapters, event)
    assert dead.status == EventStatus.DEAD
    assert dead.error == "attempt limit exceeded; last error: TransientError: upstream timeout"


def test_attempt_cap_without_a_recorded_error_says_the_worker_crashed(
    adapters: Adapters, clock: FixedClock
) -> None:
    event = claimed(adapters)
    for _ in range(MAX_ATTEMPTS):  # every claim crashed before the handler recorded anything
        clock.advance(300)
        [event] = adapters.queue.claim(clock.now(), LEASE, 1)
    assert make_pipeline(adapters).process(event) == EventStatus.DEAD
    expected = "attempt limit exceeded; last error: none recorded (worker crashed; see logs)"
    assert stored(adapters, event).error == expected


def test_the_attempt_limit_error_is_truncated_too(
    adapters: Adapters, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    fail_with(monkeypatch, TransientError("x" * 600))
    event, pipeline = claimed(adapters), make_pipeline(adapters)
    assert pipeline.process(event) == EventStatus.FAILED
    for _ in range(MAX_ATTEMPTS):
        clock.advance(300)
        [event] = adapters.queue.claim(clock.now(), LEASE, 1)
    assert pipeline.process(event) == EventStatus.DEAD
    assert len(stored(adapters, event).error or "") == 500
