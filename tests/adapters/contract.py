from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.domain.enums import FeedbackKind, SourceMode, SourceType
from feedback_ingest.domain.metadata import PlaystoreMetadata
from feedback_ingest.domain.models import FeedbackRecord, RawEvent, Source, Tenant
from feedback_ingest.ports.queue import RawEventQueue
from feedback_ingest.ports.stores import FeedbackStore, SourceStore, TenantStore


@dataclass
class Adapters:
    tenants: TenantStore
    sources: SourceStore
    feedback: FeedbackStore
    queue: RawEventQueue
    clock: FixedClock


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
    base = FeedbackRecord(
        id=uuid4().hex,
        tenant_id=src.tenant_id,
        source_id=src.id,
        source_type=src.type,
        external_id=external_id,
        kind=FeedbackKind.REVIEW,
        title=None,
        text="great app",
        author="someone",
        language="en",
        rating=5,
        source_created_at=created,
        source_updated_at=None,
        ingested_at=created,
        deleted_at=None,
        connector_version=1,
        metadata=PlaystoreMetadata(app_version="1.0", device="pixel", android_os_version=34),
    )
    return FeedbackRecord.model_validate(base.model_dump() | changes)


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


def ist(naive_utc: datetime) -> datetime:
    return naive_utc.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=5, minutes=30)))


Case = Callable[[Adapters], None]
