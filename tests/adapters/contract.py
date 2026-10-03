from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.enums import KIND_BY_SOURCE, SourceMode, SourceType
from feedback_ingest.domain.metadata import PlaystoreMetadata
from feedback_ingest.domain.models import FeedbackRecord, RawEvent, Source, Tenant

TENANT_A = Tenant(id="tenant-a", name="Acme", api_key_hash="hash-a")
TENANT_B = Tenant(id="tenant-b", name="Globex", api_key_hash="hash-b")


def source(source_id: str, tenant_id: str, mode: SourceMode = SourceMode.PUSH) -> Source:
    return Source(
        id=source_id,
        tenant_id=tenant_id,
        type=SourceType.PLAYSTORE,
        name=source_id,
        mode=mode,
        config={"package": "com.example.app"},
        webhook_secret="secret",  # noqa: S106 synthetic test secret
        cursor=None,
    )


SOURCE_A1 = source("src-a1", TENANT_A.id)
SOURCE_A2 = source("src-a2", TENANT_A.id, SourceMode.PULL)
SOURCE_B1 = source("src-b1", TENANT_B.id)


def seed(a: Adapters) -> None:
    for tenant in (TENANT_A, TENANT_B):
        a.tenants.add(tenant)
    for src in (SOURCE_A1, SOURCE_A2, SOURCE_B1):
        a.sources.add(src)


def record(src: Source, external_id: str, created: datetime, **changes: object) -> FeedbackRecord:
    base = {
        "id": uuid4().hex,
        "tenant_id": src.tenant_id,
        "source_id": src.id,
        "source_type": src.type,
        "external_id": external_id,
        "title": None,
        "text": "great app",
        "author": "someone",
        "language": "en",
        "rating": 5,
        "source_created_at": created,
        "source_updated_at": None,
        "ingested_at": created,
        "deleted_at": None,
        "connector_version": 1,
        "metadata": PlaystoreMetadata(app_version="1.0", device="pixel", android_os_version=34),
    }
    kind = KIND_BY_SOURCE[SourceType(str(changes.get("source_type", src.type)))]
    return FeedbackRecord.model_validate({"kind": kind} | base | changes)


def event(src: Source, external_event_id: str, next_attempt_at: datetime) -> RawEvent:
    return RawEvent(
        id=uuid4().hex,
        tenant_id=src.tenant_id,
        source_id=src.id,
        external_event_id=external_event_id,
        payload={"id": external_event_id},
        received_at=next_attempt_at,
        next_attempt_at=next_attempt_at,
    )


Case = Callable[[Adapters], None]
