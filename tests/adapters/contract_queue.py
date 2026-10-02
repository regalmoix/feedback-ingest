from datetime import timedelta

import pytest
from contract import SOURCE_A1, SOURCE_B1, TENANT_A, Adapters, Case, event, seed
from sqlalchemy.exc import IntegrityError

from feedback_ingest.domain.enums import EventStatus


def duplicate_enqueue_returns_the_stored_id(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    first, other_source = event(SOURCE_A1, "e1", now), event(SOURCE_B1, "e1", now)
    assert a.queue.enqueue(first) == first.id
    assert a.queue.enqueue(event(SOURCE_A1, "e1", now)) == first.id
    assert a.queue.enqueue(other_source) == other_source.id
    with pytest.raises((ValueError, IntegrityError)):
        a.queue.enqueue(first.model_copy(update={"external_event_id": "e2"}))
    assert a.queue.counts(TENANT_A.id)[EventStatus.PENDING] == 1


def claim_leases_due_rows_once(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    due = event(SOURCE_A1, "e1", now)
    a.queue.enqueue(due)
    a.queue.enqueue(event(SOURCE_A1, "e2", now + timedelta(minutes=1)))
    [claimed] = a.queue.claim(now, lease_seconds=30, limit=10)
    assert claimed.id == due.id
    assert claimed.status == EventStatus.PROCESSING
    assert claimed.lease_until == now + timedelta(seconds=30)
    assert claimed.attempts == 1
    assert a.queue.claim(now, lease_seconds=30, limit=10) == []


def claim_respects_limit(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    for name in ("e1", "e2", "e3"):
        a.queue.enqueue(event(SOURCE_A1, name, now))
    assert len(a.queue.claim(now, lease_seconds=30, limit=2)) == 2
    assert len(a.queue.claim(now, lease_seconds=30, limit=2)) == 1


def expired_lease_is_reclaimed_with_a_fresh_lease(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    a.queue.enqueue(event(SOURCE_A1, "e1", now))
    [first] = a.queue.claim(now, lease_seconds=30, limit=10)
    assert first.lease_until is not None
    assert a.queue.claim(first.lease_until, lease_seconds=30, limit=10) == []
    after = first.lease_until + timedelta(seconds=1)
    [again] = a.queue.claim(after, lease_seconds=30, limit=10)
    assert (again.id, again.attempts) == (first.id, 2)
    assert again.lease_until == after + timedelta(seconds=30)
    assert a.queue.claim(after, lease_seconds=30, limit=10) == []


def failed_waits_dead_stays_requeue_revives(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    far = now + timedelta(days=3650)
    a.queue.enqueue(event(SOURCE_A1, "e1", now))
    [claimed] = a.queue.claim(now, lease_seconds=30, limit=10)
    assert a.queue.mark_failed(claimed, "boom", now + timedelta(seconds=60))
    assert a.queue.claim(now + timedelta(seconds=59), lease_seconds=30, limit=10) == []
    [retried] = a.queue.claim(now + timedelta(seconds=60), lease_seconds=30, limit=10)
    assert a.queue.mark_dead(retried, "still boom")
    assert a.queue.claim(far, lease_seconds=30, limit=10) == []
    dead = a.queue.get(retried.id)
    assert dead is not None
    assert (dead.status, dead.error) == (EventStatus.DEAD, "still boom")
    assert a.queue.requeue(retried.id, now + timedelta(days=1))
    [revived] = a.queue.claim(now + timedelta(days=1), lease_seconds=30, limit=10)
    assert revived.attempts == 1
    assert a.queue.mark_processed(revived)
    assert [e.id for e in a.queue.list_by_status(EventStatus.PROCESSED)] == [revived.id]
    assert a.queue.claim(far, lease_seconds=30, limit=10) == []


def counts_group_by_status_per_tenant(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    for name in ("e1", "e2"):
        a.queue.enqueue(event(SOURCE_A1, name, now))
    a.queue.enqueue(event(SOURCE_B1, "e3", now + timedelta(minutes=1)))
    [claimed, _] = a.queue.claim(now, lease_seconds=30, limit=10)
    a.queue.mark_dead(claimed, "bad")
    assert a.queue.counts() == {
        EventStatus.PENDING: 1,
        EventStatus.PROCESSING: 1,
        EventStatus.PROCESSED: 0,
        EventStatus.FAILED: 0,
        EventStatus.DEAD: 1,
    }
    assert a.queue.counts(TENANT_A.id)[EventStatus.PENDING] == 0
    assert [e.id for e in a.queue.list_by_status(EventStatus.DEAD, tenant_id="other")] == []


def list_by_status_is_newest_first_then_id(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    old = event(SOURCE_A1, "e1", now)
    tied = [event(SOURCE_A1, name, now + timedelta(minutes=1)) for name in ("e2", "e3")]
    for e in (old, *tied):
        a.queue.enqueue(e)
    expected = [*sorted(e.id for e in tied), old.id]
    assert [e.id for e in a.queue.list_by_status(EventStatus.PENDING)] == expected


QUEUE_CASES: list[Case] = [
    duplicate_enqueue_returns_the_stored_id,
    claim_leases_due_rows_once,
    claim_respects_limit,
    expired_lease_is_reclaimed_with_a_fresh_lease,
    failed_waits_dead_stays_requeue_revives,
    counts_group_by_status_per_tenant,
    list_by_status_is_newest_first_then_id,
]
