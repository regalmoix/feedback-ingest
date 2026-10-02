from collections.abc import Mapping

from sqlalchemy import ColumnElement, Engine, select, update
from sqlalchemy.exc import IntegrityError

from feedback_ingest.adapters.sqlalchemy.db import sessions
from feedback_ingest.adapters.sqlalchemy.tables import SourceRow, TenantRow
from feedback_ingest.domain.enums import SourceMode
from feedback_ingest.domain.errors import NotFoundError
from feedback_ingest.domain.models import Source, Tenant


class SqlTenantStore:
    def __init__(self, engine: Engine) -> None:
        self._write, self._read = sessions(engine)

    def add(self, tenant: Tenant) -> None:
        try:
            with self._write.begin() as session:
                session.add(TenantRow(**tenant.model_dump()))
        except IntegrityError as exc:
            msg = f"duplicate tenant {tenant.name!r}"
            raise ValueError(msg) from exc

    def get_by_api_key_hash(self, api_key_hash: str) -> Tenant | None:
        with self._read.begin() as session:
            row = session.scalar(select(TenantRow).where(TenantRow.api_key_hash == api_key_hash))
            return Tenant.model_validate(row, from_attributes=True) if row else None


class SqlSourceStore:
    def __init__(self, engine: Engine) -> None:
        self._write, self._read = sessions(engine)

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
        return next(iter(found), None)

    def get_by_id(self, source_id: str) -> Source | None:
        return next(iter(self._list(SourceRow.id == source_id)), None)

    def list_for_tenant(self, tenant_id: str) -> list[Source]:
        return self._list(SourceRow.tenant_id == tenant_id)

    def list_enabled(self, mode: SourceMode) -> list[Source]:
        return self._list(SourceRow.mode == mode, SourceRow.enabled.is_(True))

    def update_cursor(self, source_id: str, tenant_id: str, cursor: str) -> None:
        self._change(source_id, tenant_id, cursor=cursor)

    def set_enabled(self, source_id: str, tenant_id: str, enabled: bool) -> None:
        self._change(source_id, tenant_id, enabled=enabled)

    def set_config(self, source_id: str, tenant_id: str, config: Mapping[str, str]) -> None:
        self._change(source_id, tenant_id, config=dict(config))

    def _change(self, source_id: str, tenant_id: str, **values: object) -> None:
        where = (SourceRow.id == source_id, SourceRow.tenant_id == tenant_id)
        stmt = update(SourceRow).where(*where).values(**values).returning(SourceRow.id)
        with self._write.begin() as session:
            if session.scalar(stmt) is None:
                raise NotFoundError(source_id)

    def _list(self, *conditions: ColumnElement[bool]) -> list[Source]:
        with self._read.begin() as session:
            rows = session.scalars(select(SourceRow).where(*conditions).order_by(SourceRow.id))
            return [Source.model_validate(row, from_attributes=True) for row in rows]
