from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, Engine, and_, func, or_, select, update
from sqlalchemy.orm import sessionmaker

from feedback_ingest.adapters.sqlalchemy.tables import RawEventRow
from feedback_ingest.domain.enums import EventStatus
from feedback_ingest.domain.errors import check_limit
from feedback_ingest.domain.models import RawEvent
from feedback_ingest.utils.time import to_naive_utc

_RETRYABLE = (EventStatus.PENDING, EventStatus.FAILED)


class SqlRawEventQueue:
    def __init__(self, engine: Engine) -> None:
        self._write = sessionmaker(engine, expire_on_commit=False)
        self._read = sessionmaker(engine.execution_options(read_only=True), expire_on_commit=False)

    def enqueue(self, event: RawEvent) -> bool:
        with self._write.begin() as session:
            key = {"source_id": event.source_id, "external_event_id": event.external_event_id}
            if session.scalar(select(RawEventRow.id).filter_by(**key)) is not None:
                return False
            session.add(RawEventRow(**event.model_dump()))
        return True

    # ponytail: claimable predicate repeated on the outer UPDATE keeps it race-safe on SQLite and
    # Postgres READ COMMITTED; add FOR UPDATE SKIP LOCKED on Postgres for many workers
    def claim(self, now: datetime, lease_seconds: int, limit: int) -> list[RawEvent]:
        if limit < 1 or lease_seconds < 1:
            msg = "limit and lease_seconds must be >= 1"
            raise ValueError(msg)
        now = to_naive_utc(now)
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
        return self._finish(
            event,
            status=EventStatus.FAILED,
            error=error,
            next_attempt_at=to_naive_utc(next_attempt_at),
        )

    def mark_dead(self, event: RawEvent, error: str) -> bool:
        return self._finish(event, status=EventStatus.DEAD, error=error)

    def requeue(self, event_id: str, now: datetime) -> bool:
        return self._set(
            RawEventRow.id == event_id,
            RawEventRow.status != EventStatus.PROCESSING,
            status=EventStatus.PENDING,
            attempts=0,
            next_attempt_at=to_naive_utc(now),
            lease_until=None,
            error=None,
        )

    def get(self, event_id: str) -> RawEvent | None:
        with self._read.begin() as session:
            row = session.get(RawEventRow, event_id)
            return RawEvent.model_validate(row, from_attributes=True) if row else None

    def list_by_status(
        self, status: EventStatus, *, tenant_id: str | None = None, limit: int = 100
    ) -> list[RawEvent]:
        query = select(RawEventRow).where(RawEventRow.status == status)
        if tenant_id is not None:
            query = query.where(RawEventRow.tenant_id == tenant_id)
        query = query.order_by(RawEventRow.received_at, RawEventRow.id).limit(check_limit(limit))
        with self._read.begin() as session:
            return [
                RawEvent.model_validate(r, from_attributes=True) for r in session.scalars(query)
            ]

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
