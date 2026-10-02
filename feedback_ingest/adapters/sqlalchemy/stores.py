from datetime import datetime

from sqlalchemy import ColumnElement, Engine, select, update
from sqlalchemy.orm import sessionmaker

from feedback_ingest.adapters.sqlalchemy.tables import FeedbackRecordRow, SourceRow, TenantRow
from feedback_ingest.domain.enums import FeedbackKind, SourceMode, UpsertOutcome
from feedback_ingest.domain.errors import NotFoundError
from feedback_ingest.domain.models import FeedbackRecord, Source, Tenant
from feedback_ingest.utils.time import to_naive_utc


class SqlTenantStore:
    def __init__(self, engine: Engine) -> None:
        self._write = sessionmaker(engine, expire_on_commit=False)
        self._read = sessionmaker(engine.execution_options(read_only=True), expire_on_commit=False)

    def add(self, tenant: Tenant) -> None:
        with self._write.begin() as session:
            session.add(TenantRow(**tenant.model_dump()))

    def get_by_api_key_hash(self, api_key_hash: str) -> Tenant | None:
        with self._read.begin() as session:
            row = session.scalar(select(TenantRow).where(TenantRow.api_key_hash == api_key_hash))
            return Tenant.model_validate(row, from_attributes=True) if row else None


class SqlSourceStore:
    def __init__(self, engine: Engine) -> None:
        self._write = sessionmaker(engine, expire_on_commit=False)
        self._read = sessionmaker(engine.execution_options(read_only=True), expire_on_commit=False)

    def add(self, source: Source) -> None:
        secret = source.webhook_secret
        row = SourceRow(
            **source.model_dump(exclude={"webhook_secret"}),
            webhook_secret=secret.get_secret_value() if secret is not None else None,
        )
        with self._write.begin() as session:
            session.add(row)

    def get(self, source_id: str, tenant_id: str) -> Source | None:
        found = self._list(SourceRow.id == source_id, SourceRow.tenant_id == tenant_id)
        return found[0] if found else None

    def list_for_tenant(self, tenant_id: str) -> list[Source]:
        return self._list(SourceRow.tenant_id == tenant_id)

    def list_by_mode(self, mode: SourceMode) -> list[Source]:
        return self._list(SourceRow.mode == mode)

    def update_cursor(self, source_id: str, cursor: str) -> None:
        stmt = update(SourceRow).where(SourceRow.id == source_id).values(cursor=cursor)
        with self._write.begin() as session:
            if session.scalar(stmt.returning(SourceRow.id)) is None:
                raise NotFoundError(source_id)

    def _list(self, *conditions: ColumnElement[bool]) -> list[Source]:
        with self._read.begin() as session:
            rows = session.scalars(select(SourceRow).where(*conditions).order_by(SourceRow.id))
            return [Source.model_validate(row, from_attributes=True) for row in rows]


class SqlFeedbackStore:
    def __init__(self, engine: Engine) -> None:
        self._write = sessionmaker(engine, expire_on_commit=False)
        self._read = sessionmaker(engine.execution_options(read_only=True), expire_on_commit=False)

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
            query = query.where(FeedbackRecordRow.source_created_at >= to_naive_utc(since))
        if not include_deleted:
            query = query.where(FeedbackRecordRow.deleted_at.is_(None))
        query = query.order_by(FeedbackRecordRow.source_created_at, FeedbackRecordRow.id)
        with self._read.begin() as session:
            return [_to_record(row) for row in session.scalars(query.limit(limit))]


def _to_record(row: FeedbackRecordRow) -> FeedbackRecord:
    data = {attr.key: getattr(row, attr.key) for attr in FeedbackRecordRow.__mapper__.column_attrs}
    data["metadata"] = data.pop("source_metadata")
    return FeedbackRecord.model_validate(data)
