from datetime import datetime
from typing import Protocol

from feedback_ingest.domain.enums import FeedbackKind, SourceMode, UpsertOutcome
from feedback_ingest.domain.models import FeedbackRecord, Source, Tenant


class TenantStore(Protocol):
    def add(self, tenant: Tenant) -> None: ...
    def get_by_api_key_hash(self, api_key_hash: str) -> Tenant | None: ...


class SourceStore(Protocol):
    def add(self, source: Source) -> None: ...
    def get(self, source_id: str, tenant_id: str) -> Source | None: ...
    def list_for_tenant(self, tenant_id: str) -> list[Source]: ...
    def list_by_mode(self, mode: SourceMode) -> list[Source]: ...
    def update_cursor(self, source_id: str, cursor: str) -> None: ...


class FeedbackStore(Protocol):
    def upsert(self, record: FeedbackRecord) -> UpsertOutcome: ...
    def list_for_tenant(  # noqa: PLR0913  keyword-only query filters
        self,
        tenant_id: str,
        *,
        source_id: str | None = None,
        kind: FeedbackKind | None = None,
        since: datetime | None = None,
        limit: int = 100,
        include_deleted: bool = False,
    ) -> list[FeedbackRecord]: ...
