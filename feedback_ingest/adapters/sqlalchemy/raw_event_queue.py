from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, Engine, and_, func, or_, select, update

from feedback_ingest.adapters.sqlalchemy.db import sessions
from feedback_ingest.adapters.sqlalchemy.tables import RawEventRow
from feedback_ingest.domain.enums import EventStatus
from feedback_ingest.domain.errors import check_limit
from feedback_ingest.domain.models import Enqueued, RawEvent
from feedback_ingest.ports.queue import RawEventQueue

_RETRYABLE = (EventStatus.PENDING, EventStatus.FAILED)


class SqlRawEventQueue(RawEventQueue):
    def __init__(self, engine: Engine) -> None:
        self._write, self._read = sessions(engine)

    def enqueue(self, event: RawEvent) -> Enqueued:
        with self._write.begin() as session:
            key = {"source_id": event.source_id, "external_event_id": event.external_event_id}
            stored = session.execute(
                select(RawEventRow.id, RawEventRow.status).filter_by(**key)
            ).one_or_none()
            if stored is not None:
                return Enqueued(stored.id, EventStatus(stored.status))
            session.add(RawEventRow(**event.model_dump()))
        return Enqueued(event.id, event.status)

    # ponytail: claimable predicate repeated on the outer UPDATE keeps it race-safe on SQLite and
    # Postgres READ COMMITTED; add FOR UPDATE SKIP LOCKED on Postgres for many workers
    def claim(self, now: datetime, lease_seconds: int, limit: int) -> list[RawEvent]:
        if limit < 1 or lease_seconds < 1:
            msg = "limit and lease_seconds must be >= 1"
            raise ValueError(msg)
        claimable = or_(
            and_(RawEventRow.status.in_(_RETRYABLE), RawEventRow.next_attempt_at <= now),
            and_(RawEventRow.status == EventStatus.PROCESSING, RawEventRow.lease_until < now),
        )
        due = select(RawEventRow.id).where(claimable).order_by(RawEventRow.next_attempt_at)
        claim = (
            update(RawEventRow)
            .where(RawEventRow.id.in_(due.limit(limit).scalar_subquery()), claimable)
            .values(
                status=EventStatus.PROCESSING,
                lease_until=now + timedelta(seconds=lease_seconds),
                attempts=RawEventRow.attempts + 1,
            )
            .returning(RawEventRow)
            .execution_options(synchronize_session=False)
        )
        with self._write.begin() as session:
            rows = session.scalars(claim).all()
            events = [RawEvent.model_validate(row, from_attributes=True) for row in rows]
        return sorted(events, key=lambda event: event.next_attempt_at)

    def mark_processed(self, event: RawEvent) -> bool:
        return self._finish(event, status=EventStatus.PROCESSED, error=None)

    def mark_failed(self, event: RawEvent, error: str, next_attempt_at: datetime) -> bool:
        retry = {"error": error, "next_attempt_at": next_attempt_at}
        return self._finish(event, status=EventStatus.FAILED, **retry)

    def mark_dead(self, event: RawEvent, error: str) -> bool:
        return self._finish(event, status=EventStatus.DEAD, error=error)

    def replay(self, event_id: str, now: datetime) -> bool:
        return self._set(
            RawEventRow.id == event_id,
            or_(RawEventRow.status != EventStatus.PROCESSING, RawEventRow.lease_until < now),
            status=EventStatus.PENDING,
            attempts=0,
            next_attempt_at=now,
            lease_until=None,
            error=None,
        )

    def get(self, event_id: str) -> RawEvent | None:
        with self._read.begin() as session:
            row = session.get(RawEventRow, event_id)
            return RawEvent.model_validate(row, from_attributes=True) if row else None

    def list_by_status(
        self,
        status: EventStatus,
        *,
        tenant_id: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[RawEvent]:
        scope = {"tenant_id": tenant_id, "source_id": source_id}
        query = select(RawEventRow).filter_by(
            status=status, **{key: value for key, value in scope.items() if value is not None}
        )
        newest_first = (RawEventRow.received_at.desc(), RawEventRow.id)
        query = query.order_by(*newest_first).limit(check_limit(limit))
        with self._read.begin() as session:
            rows = session.scalars(query)
            return [RawEvent.model_validate(r, from_attributes=True) for r in rows]

    def counts(self, tenant_id: str | None = None) -> dict[EventStatus, int]:
        query = select(RawEventRow.status, func.count()).group_by(RawEventRow.status)
        if tenant_id is not None:
            query = query.where(RawEventRow.tenant_id == tenant_id)
        with self._read.begin() as session:
            found = {EventStatus(status): count for status, count in session.execute(query)}
        return dict.fromkeys(EventStatus, 0) | found

    def _finish(self, event: RawEvent, **values: object) -> bool:
        fence = (
            RawEventRow.status == EventStatus.PROCESSING,
            RawEventRow.attempts == event.attempts,
            RawEventRow.lease_until == event.lease_until,
        )
        return self._set(RawEventRow.id == event.id, *fence, lease_until=None, **values)

    def _set(self, *conditions: ColumnElement[bool], **values: object) -> bool:
        stmt = update(RawEventRow).where(*conditions).values(**values).returning(RawEventRow.id)
        with self._write.begin() as session:
            return session.scalar(stmt) is not None
