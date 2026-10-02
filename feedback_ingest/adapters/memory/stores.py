from datetime import datetime

from feedback_ingest.domain.enums import FeedbackKind, SourceMode, UpsertOutcome
from feedback_ingest.domain.errors import NotFoundError, check_limit
from feedback_ingest.domain.models import FeedbackRecord, Source, Tenant


class MemoryTenantStore:
    def __init__(self) -> None:
        self._tenants: dict[str, Tenant] = {}

    def add(self, tenant: Tenant) -> None:
        taken = any(t.name == tenant.name for t in self._tenants.values())
        if taken or tenant.id in self._tenants or self.get_by_api_key_hash(tenant.api_key_hash):
            msg = f"duplicate tenant {tenant.name!r}"
            raise ValueError(msg)
        self._tenants[tenant.id] = tenant

    def get_by_api_key_hash(self, api_key_hash: str) -> Tenant | None:
        return next((t for t in self._tenants.values() if t.api_key_hash == api_key_hash), None)


class MemorySourceStore:
    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}

    def add(self, source: Source) -> None:
        if source.id in self._sources:
            msg = f"duplicate source {source.id}"
            raise ValueError(msg)
        self._sources[source.id] = source

    def get(self, source_id: str, tenant_id: str) -> Source | None:
        source = self._sources.get(source_id)
        return source if source and source.tenant_id == tenant_id else None

    def get_by_id(self, source_id: str) -> Source | None:
        return self._sources.get(source_id)

    def list_for_tenant(self, tenant_id: str) -> list[Source]:
        return sorted(
            (s for s in self._sources.values() if s.tenant_id == tenant_id), key=lambda s: s.id
        )

    def list_by_mode(self, mode: SourceMode) -> list[Source]:
        return sorted(
            (s for s in self._sources.values() if s.mode == mode and s.enabled), key=lambda s: s.id
        )

    def update_cursor(self, source_id: str, cursor: str) -> None:
        if source_id not in self._sources:
            raise NotFoundError(source_id)
        self._sources[source_id] = self._sources[source_id].model_copy(update={"cursor": cursor})

    def set_enabled(self, source_id: str, tenant_id: str, enabled: bool) -> None:
        source = self.get(source_id, tenant_id)
        if source is None:
            raise NotFoundError(source_id)
        self._sources[source_id] = source.model_copy(update={"enabled": enabled})


# ponytail: no FK check in the fake; the SQLite contract test covers tenant mismatch
class MemoryFeedbackStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], FeedbackRecord] = {}

    def upsert(self, record: FeedbackRecord) -> UpsertOutcome:
        key = (record.source_id, record.external_id)
        existing = self._records.get(key)
        if existing is None:
            self._records[key] = record
            return UpsertOutcome.INSERTED
        if record.version_at < existing.version_at:
            if record.deleted_at is None or existing.deleted_at is not None:
                return UpsertOutcome.SKIPPED_OLDER
            self._records[key] = existing.model_copy(update={"deleted_at": record.deleted_at})
            return UpsertOutcome.UPDATED
        self._records[key] = record.model_copy(
            update={
                "id": existing.id,
                "source_created_at": existing.source_created_at,
                "source_updated_at": record.version_at,
                "ingested_at": existing.ingested_at,
                "deleted_at": existing.deleted_at or record.deleted_at,
            }
        )
        return UpsertOutcome.UPDATED

    def get(self, record_id: str, tenant_id: str) -> FeedbackRecord | None:
        return next(
            (r for r in self._records.values() if r.id == record_id and r.tenant_id == tenant_id),
            None,
        )

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
        matches = [
            r
            for r in self._records.values()
            if r.tenant_id == tenant_id
            and (source_id is None or r.source_id == source_id)
            and (kind is None or r.kind == kind)
            and (since is None or r.source_created_at >= since)
            and (include_deleted or r.deleted_at is None)
        ]
        return sorted(matches, key=lambda r: (r.source_created_at, r.id))[: check_limit(limit)]
