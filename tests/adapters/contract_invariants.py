from datetime import timedelta

import pytest
from contract import SOURCE_A1, Case, event, seed
from sqlalchemy.exc import IntegrityError

from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.models import Tenant


def replay_clears_the_old_error(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    a.queue.enqueue(event(SOURCE_A1, "e1", now))
    [claimed] = a.queue.claim(now, lease_seconds=30, limit=10)
    assert a.queue.mark_dead(claimed, "bad")
    assert a.queue.replay(claimed.id, now)
    stored = a.queue.get(claimed.id)
    assert stored is not None
    assert (stored.error, stored.lease_until) == (None, None)


def claim_returns_the_oldest_due_first(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    events = [event(SOURCE_A1, f"e{m}", now - timedelta(minutes=m)) for m in (3, 9, 1)]
    for e in events:
        a.queue.enqueue(e)
    oldest_first = [e.id for e in sorted(events, key=lambda e: e.next_attempt_at)]
    assert [e.id for e in a.queue.claim(now, lease_seconds=30, limit=10)] == oldest_first


def an_api_key_hash_belongs_to_one_tenant(a: Adapters) -> None:
    seed(a)
    with pytest.raises(ValueError, match="duplicate tenant"):
        a.tenants.add(Tenant(id="tenant-c", name="Initech", api_key_hash="hash-a"))


def a_reused_event_id_with_a_new_key_is_refused(a: Adapters) -> None:
    seed(a)
    first = event(SOURCE_A1, "e1", a.clock.now())
    a.queue.enqueue(first)
    with pytest.raises((ValueError, IntegrityError)):
        a.queue.enqueue(first.model_copy(update={"external_event_id": "e2"}))


INVARIANT_CASES: list[Case] = [
    replay_clears_the_old_error,
    claim_returns_the_oldest_due_first,
    an_api_key_hash_belongs_to_one_tenant,
    a_reused_event_id_with_a_new_key_is_refused,
]
