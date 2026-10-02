from datetime import datetime, timedelta

from feedback_ingest.domain.enums import EventStatus
from feedback_ingest.domain.models import RawEvent
from feedback_ingest.utils.time import to_naive_utc

_RETRYABLE = (EventStatus.PENDING, EventStatus.FAILED)


class MemoryRawEventQueue:
    def __init__(self) -> None:
        self._events: dict[str, RawEvent] = {}

    def enqueue(self, event: RawEvent) -> bool:
        key = (event.source_id, event.external_event_id)
        if any((e.source_id, e.external_event_id) == key for e in self._events.values()):
            return False
        if event.id in self._events:
            msg = f"duplicate raw event id {event.id}"
            raise ValueError(msg)
        self._events[event.id] = event
        return True

    def claim(self, now: datetime, lease_seconds: int, limit: int) -> list[RawEvent]:
        if limit < 1 or lease_seconds < 1:
            msg = "limit and lease_seconds must be >= 1"
            raise ValueError(msg)
        now = to_naive_utc(now)
        due = sorted(
            (e for e in self._events.values() if _is_claimable(e, now)),
            key=lambda e: e.next_attempt_at,
        )[:limit]
        lease_until = now + timedelta(seconds=lease_seconds)
        for event in due:
            self._update(
                event.id,
                status=EventStatus.PROCESSING,
                lease_until=lease_until,
                attempts=event.attempts + 1,
            )
        return [self._events[e.id] for e in due]

    def mark_processed(self, event: RawEvent) -> bool:
        return self._finish(event, status=EventStatus.PROCESSED, error=None)

    def mark_failed(self, event: RawEvent, error: str, next_attempt_at: datetime) -> bool:
        return self._finish(
            event,
            status=EventStatus.FAILED,
            error=error,
            next_attempt_at=to_naive_utc(next_attempt_at),
        )

    def mark_dead(self, event: RawEvent, error: str) -> bool:
        return self._finish(event, status=EventStatus.DEAD, error=error)

    def requeue(self, event_id: str, now: datetime) -> bool:
        event = self._events.get(event_id)
        if event is None or event.status == EventStatus.PROCESSING:
            return False
        self._update(
            event_id,
            status=EventStatus.PENDING,
            attempts=0,
            next_attempt_at=to_naive_utc(now),
            lease_until=None,
            error=None,
        )
        return True

    def get(self, event_id: str) -> RawEvent | None:
        return self._events.get(event_id)

    def list_by_status(
        self, status: EventStatus, *, tenant_id: str | None = None, limit: int = 100
    ) -> list[RawEvent]:
        matches = [
            e
            for e in self._events.values()
            if e.status == status and (tenant_id is None or e.tenant_id == tenant_id)
        ]
        return sorted(matches, key=lambda e: (e.received_at, e.id))[:limit]

    def counts(self, tenant_id: str | None = None) -> dict[EventStatus, int]:
        result = dict.fromkeys(EventStatus, 0)
        for event in self._events.values():
            if tenant_id is None or event.tenant_id == tenant_id:
                result[event.status] += 1
        return result

    def _finish(self, event: RawEvent, **changes: object) -> bool:
        stored = self._events.get(event.id)
        fence = (EventStatus.PROCESSING, event.attempts, event.lease_until)
        if stored is None or (stored.status, stored.attempts, stored.lease_until) != fence:
            return False
        self._update(event.id, lease_until=None, **changes)
        return True

    def _update(self, event_id: str, **changes: object) -> None:
        existing = self._events[event_id]
        self._events[event_id] = RawEvent.model_validate(existing.model_dump() | changes)


def _is_claimable(event: RawEvent, now: datetime) -> bool:
    if event.status in _RETRYABLE:
        return event.next_attempt_at <= now
    lease_until = event.lease_until
    return event.status == EventStatus.PROCESSING and lease_until is not None and lease_until < now
