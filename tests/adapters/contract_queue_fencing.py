from datetime import timedelta

import pytest
from contract import SOURCE_A1, Adapters, Case, event, seed

from feedback_ingest.domain.enums import EventStatus


def stale_worker_cannot_finish(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    a.queue.enqueue(event(SOURCE_A1, "e1", now))
    [mine] = a.queue.claim(now, lease_seconds=30, limit=10)
    later = now + timedelta(seconds=31)
    [theirs] = a.queue.claim(later, lease_seconds=30, limit=10)
    assert a.queue.mark_processed(theirs) is True
    assert a.queue.mark_dead(mine, "late") is False
    assert a.queue.mark_failed(mine, "late", later) is False
    stored = a.queue.get(mine.id)
    assert stored is not None
    assert (stored.status, stored.error) == (EventStatus.PROCESSED, None)


def requeue_and_marks_are_checked(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    a.queue.enqueue(event(SOURCE_A1, "e1", now))
    [claimed] = a.queue.claim(now, lease_seconds=30, limit=10)
    assert claimed.lease_until is not None
    assert a.queue.requeue(claimed.id, claimed.lease_until) is False  # the lease is live
    stored = a.queue.get(claimed.id)
    assert stored is not None
    assert stored.status == EventStatus.PROCESSING
    ghost = claimed.model_copy(update={"id": "missing"})
    assert a.queue.mark_processed(ghost) is False
    assert a.queue.mark_failed(ghost, "x", now) is False
    assert a.queue.mark_dead(ghost, "x") is False
    assert a.queue.requeue("missing", now) is False
    expired = claimed.lease_until + timedelta(seconds=1)  # the worker crashed
    assert a.queue.requeue(claimed.id, expired) is True
    stored = a.queue.get(claimed.id)
    assert stored is not None
    assert (stored.status, stored.attempts, stored.next_attempt_at) == (
        EventStatus.PENDING,
        0,
        expired,
    )
    assert a.queue.mark_processed(claimed) is False


def requeued_row_is_fenced_from_the_first_worker(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    later = now + timedelta(seconds=31)
    a.queue.enqueue(event(SOURCE_A1, "e1", now))
    [first] = a.queue.claim(now, lease_seconds=30, limit=10)
    [second] = a.queue.claim(later, lease_seconds=30, limit=10)
    assert a.queue.mark_dead(second, "bad")
    assert a.queue.requeue(second.id, later)
    [third] = a.queue.claim(later, lease_seconds=30, limit=10)
    assert third.attempts == first.attempts
    assert a.queue.mark_processed(first) is False
    stored = a.queue.get(first.id)
    assert stored is not None
    assert stored.status == EventStatus.PROCESSING
    assert a.queue.mark_processed(third) is True


def claim_rejects_non_positive_limit_and_lease(a: Adapters) -> None:
    now = a.clock.now()
    for limit, lease_seconds in ((0, 30), (-1, 30), (10, 0)):
        with pytest.raises(ValueError, match=">= 1"):
            a.queue.claim(now, lease_seconds=lease_seconds, limit=limit)


FENCING_CASES: list[Case] = [
    stale_worker_cannot_finish,
    requeue_and_marks_are_checked,
    requeued_row_is_fenced_from_the_first_worker,
    claim_rejects_non_positive_limit_and_lease,
]
