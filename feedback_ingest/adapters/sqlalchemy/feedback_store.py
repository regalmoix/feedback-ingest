from datetime import datetime

from sqlalchemy import Engine, select

from feedback_ingest.adapters.sqlalchemy.db import sessions
from feedback_ingest.adapters.sqlalchemy.tables import FeedbackRecordRow
from feedback_ingest.domain.enums import FeedbackKind, UpsertOutcome
from feedback_ingest.domain.errors import check_limit
from feedback_ingest.domain.models import FeedbackRecord


class SqlFeedbackStore:
    def __init__(self, engine: Engine) -> None:
        self._write, self._read = sessions(engine)

    # ponytail: read-then-write under BEGIN IMMEDIATE serialises all writers;
    # switch to INSERT…ON CONFLICT when Postgres needs concurrent writers
    def upsert(self, record: FeedbackRecord) -> UpsertOutcome:
        fields: dict[str, object] = record.model_dump(exclude={"metadata"})
        fields["source_metadata"] = record.metadata.model_dump(mode="json")
        key = {"source_id": record.source_id, "external_id": record.external_id}
        with self._write.begin() as session:
            row = session.scalar(select(FeedbackRecordRow).filter_by(**key))
            if row is None:
                session.add(FeedbackRecordRow(**fields))
                return UpsertOutcome.INSERTED
            if record.version_at < (row.source_updated_at or row.source_created_at):
                if record.deleted_at is None or row.deleted_at is not None:
                    return UpsertOutcome.SKIPPED_OLDER
                row.deleted_at = record.deleted_at
                return UpsertOutcome.UPDATED
            for store_owned in ("id", "source_created_at", "ingested_at"):
                del fields[store_owned]
            fields["deleted_at"] = row.deleted_at or record.deleted_at
            fields["source_updated_at"] = record.version_at
            for name, value in fields.items():
                setattr(row, name, value)
            return UpsertOutcome.UPDATED

    def get(self, record_id: str, tenant_id: str) -> FeedbackRecord | None:
        query = select(FeedbackRecordRow).filter_by(id=record_id, tenant_id=tenant_id)
        with self._read.begin() as session:
            row = session.scalar(query)
            return _to_record(row) if row else None

    def list_for_tenant(  # noqa: PLR0913  keyword-only query filters
        self,
        tenant_id: str,
        *,
        source_id: str | None = None,
        kind: FeedbackKind | None = None,
        since: datetime | None = None,
        limit: int = 100,
        include_deleted: bool = False,
    ) -> list[FeedbackRecord]:
        query = select(FeedbackRecordRow).where(FeedbackRecordRow.tenant_id == tenant_id)
        if source_id is not None:
            query = query.where(FeedbackRecordRow.source_id == source_id)
        if kind is not None:
            query = query.where(FeedbackRecordRow.kind == kind)
        if since is not None:
            query = query.where(FeedbackRecordRow.source_created_at >= since)
        if not include_deleted:
            query = query.where(FeedbackRecordRow.deleted_at.is_(None))
        query = query.order_by(FeedbackRecordRow.source_created_at, FeedbackRecordRow.id)
        with self._read.begin() as session:
            return [_to_record(row) for row in session.scalars(query.limit(check_limit(limit)))]


def _to_record(row: FeedbackRecordRow) -> FeedbackRecord:
    data = {attr.key: getattr(row, attr.key) for attr in FeedbackRecordRow.__mapper__.column_attrs}
    data["metadata"] = data.pop("source_metadata")
    return FeedbackRecord.model_validate(data)
