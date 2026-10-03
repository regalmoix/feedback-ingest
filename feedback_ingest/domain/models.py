from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, NamedTuple, Self

from pydantic import Field, SecretStr, StringConstraints, model_validator

from feedback_ingest.domain import enums
from feedback_ingest.domain.enums import EventStatus, FeedbackKind, SourceMode, SourceType
from feedback_ingest.domain.metadata import FrozenModel, SourceMetadata
from feedback_ingest.utils.time import NaiveUtc

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Tenant(FrozenModel):
    id: str
    name: Name
    api_key_hash: str


class Source(FrozenModel):
    id: str
    tenant_id: str
    type: SourceType
    name: Name
    mode: SourceMode
    config: Mapping[str, str]
    webhook_secret: SecretStr | None = None
    cursor: str | None
    enabled: bool = True

    @model_validator(mode="after")
    def _push_needs_secret(self) -> Self:
        secret = self.webhook_secret
        if self.mode is SourceMode.PUSH and not (secret and secret.get_secret_value()):
            msg = "a push source needs a webhook_secret"
            raise ValueError(msg)
        return self


class RawEvent(FrozenModel):
    id: str
    tenant_id: str
    source_id: str
    external_event_id: str
    payload: Mapping[str, Any]
    received_at: NaiveUtc
    status: EventStatus = EventStatus.PENDING
    attempts: int = Field(default=0, ge=0)
    next_attempt_at: NaiveUtc
    lease_until: NaiveUtc | None = None
    error: str | None = None

    @model_validator(mode="after")
    def _lease_iff_processing(self) -> Self:
        if (self.lease_until is not None) != (self.status is EventStatus.PROCESSING):
            msg = "lease_until is set exactly when status is processing"
            raise ValueError(msg)
        return self


class Enqueued(NamedTuple):
    id: str  # the stored row's, new or existing
    status: EventStatus


class FeedbackRecord(FrozenModel):
    id: str
    tenant_id: str
    source_id: str
    source_type: SourceType
    kind: FeedbackKind
    external_id: str
    title: str | None
    text: str
    author: str | None
    language: str | None
    rating: Annotated[int, Field(ge=1, le=5)] | None
    source_created_at: NaiveUtc
    source_updated_at: NaiveUtc | None
    ingested_at: NaiveUtc
    deleted_at: NaiveUtc | None
    connector_version: int = Field(ge=1)
    metadata: SourceMetadata

    @model_validator(mode="after")
    def _source_type_agrees(self) -> Self:
        if self.metadata.source_type != self.source_type:
            msg = f"metadata is for {self.metadata.source_type}, record is {self.source_type}"
            raise ValueError(msg)
        expected = enums.KIND_BY_SOURCE.get(self.source_type)  # None: custom picks per record type
        if expected is not None and self.kind != expected:
            msg = f"a {self.source_type} record is a {expected}, not {self.kind}"
            raise ValueError(msg)
        return self

    @property
    def version_at(self) -> datetime:
        return self.source_updated_at or self.source_created_at


# older loses, but a delete always applies; the store owns id, first-seen and ingested_at
def merge(
    existing: FeedbackRecord, incoming: FeedbackRecord
) -> tuple[FeedbackRecord, enums.UpsertOutcome]:
    if incoming.version_at < existing.version_at:
        if incoming.deleted_at is None or existing.deleted_at is not None:
            return existing, enums.UpsertOutcome.SKIPPED_OLDER
        deleted = existing.model_copy(update={"deleted_at": incoming.deleted_at})
        return deleted, enums.UpsertOutcome.UPDATED
    kept = {
        "id": existing.id,
        "source_created_at": existing.source_created_at,
        "ingested_at": existing.ingested_at,
        "source_updated_at": incoming.version_at,  # the version only moves forward
        "deleted_at": existing.deleted_at or incoming.deleted_at,
    }
    return incoming.model_copy(update=kept), enums.UpsertOutcome.UPDATED
