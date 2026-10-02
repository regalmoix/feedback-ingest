from sqlalchemy import ColumnElement, Engine, select, update
from sqlalchemy.orm import sessionmaker

from feedback_ingest.adapters.sqlalchemy.feedback_store import SqlFeedbackStore
from feedback_ingest.adapters.sqlalchemy.tables import SourceRow, TenantRow
from feedback_ingest.domain.enums import SourceMode
from feedback_ingest.domain.errors import NotFoundError
from feedback_ingest.domain.models import Source, Tenant

__all__ = ["SqlFeedbackStore", "SqlSourceStore", "SqlTenantStore"]


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
        return self._list(SourceRow.mode == mode, SourceRow.enabled.is_(True))

    def update_cursor(self, source_id: str, cursor: str) -> None:
        stmt = update(SourceRow).where(SourceRow.id == source_id).values(cursor=cursor)
        with self._write.begin() as session:
            if session.scalar(stmt.returning(SourceRow.id)) is None:
                raise NotFoundError(source_id)

    def set_enabled(self, source_id: str, tenant_id: str, enabled: bool) -> None:
        stmt = (
            update(SourceRow)
            .where(SourceRow.id == source_id, SourceRow.tenant_id == tenant_id)
            .values(enabled=enabled)
        )
        with self._write.begin() as session:
            if session.scalar(stmt.returning(SourceRow.id)) is None:
                raise NotFoundError(source_id)

    def _list(self, *conditions: ColumnElement[bool]) -> list[Source]:
        with self._read.begin() as session:
            rows = session.scalars(select(SourceRow).where(*conditions).order_by(SourceRow.id))
            return [Source.model_validate(row, from_attributes=True) for row in rows]
