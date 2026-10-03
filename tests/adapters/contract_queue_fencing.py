from datetime import timedelta

import pytest
from contract import SOURCE_A1, Case, event, seed

from feedback_ingest.api.deps import Adapters
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


def replay_and_marks_are_checked(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    a.queue.enqueue(event(SOURCE_A1, "e1", now))
    [claimed] = a.queue.claim(now, lease_seconds=30, limit=10)
    assert claimed.lease_until is not None
    assert a.queue.replay(claimed.id, claimed.lease_until) is False  # the lease is live
    stored = a.queue.get(claimed.id)
    assert stored is not None
    assert stored.status == EventStatus.PROCESSING
    ghost = claimed.model_copy(update={"id": "missing"})
    assert a.queue.mark_processed(ghost) is False
    assert a.queue.mark_failed(ghost, "x", now) is False
    assert a.queue.mark_dead(ghost, "x") is False
    assert a.queue.replay("missing", now) is False
    expired = claimed.lease_until + timedelta(seconds=1)  # the worker crashed
    assert a.queue.replay(claimed.id, expired) is True
    stored = a.queue.get(claimed.id)
    assert stored is not None
    assert (stored.status, stored.attempts, stored.next_attempt_at) == (
        EventStatus.PENDING,
        0,
        expired,
    )
    assert a.queue.mark_processed(claimed) is False


def replayed_row_is_fenced_from_the_first_worker(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    later = now + timedelta(seconds=31)
    a.queue.enqueue(event(SOURCE_A1, "e1", now))
    [first] = a.queue.claim(now, lease_seconds=30, limit=10)
    [second] = a.queue.claim(later, lease_seconds=30, limit=10)
    assert a.queue.mark_dead(second, "bad")
    assert a.queue.replay(second.id, later)
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


def claim_takes_the_earliest_due_row_whatever_its_status(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    a.queue.enqueue(event(SOURCE_A1, "e1", now))  # first in insertion and in the status index
    [failed] = a.queue.claim(now, lease_seconds=30, limit=1)
    assert a.queue.mark_failed(failed, "boom", now + timedelta(seconds=20))
    pending = event(SOURCE_A1, "e2", now + timedelta(seconds=10))
    a.queue.enqueue(pending)
    [claimed] = a.queue.claim(now + timedelta(seconds=30), lease_seconds=30, limit=1)
    assert claimed.id == pending.id


def duplicate_enqueue_reports_the_stored_status(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    first = event(SOURCE_A1, "e1", now)
    a.queue.enqueue(first)
    [claimed] = a.queue.claim(now, lease_seconds=30, limit=10)
    assert a.queue.enqueue(event(SOURCE_A1, "e1", now)) == (first.id, EventStatus.PROCESSING)
    assert a.queue.mark_dead(claimed, "bad")
    assert a.queue.enqueue(event(SOURCE_A1, "e1", now)) == (first.id, EventStatus.DEAD)


FENCING_CASES: list[Case] = [
    duplicate_enqueue_reports_the_stored_status,
    stale_worker_cannot_finish,
    replay_and_marks_are_checked,
    replayed_row_is_fenced_from_the_first_worker,
    claim_rejects_non_positive_limit_and_lease,
    claim_takes_the_earliest_due_row_whatever_its_status,
]
