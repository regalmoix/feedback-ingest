from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Self

from pydantic import Field, SecretStr, model_validator

from feedback_ingest.domain.enums import EventStatus, FeedbackKind, SourceMode, SourceType
from feedback_ingest.domain.metadata import FrozenModel, SourceMetadata
from feedback_ingest.utils.time import NaiveUtc

KIND_BY_SOURCE: dict[SourceType, FeedbackKind] = {
    SourceType.PLAYSTORE: FeedbackKind.REVIEW,
    SourceType.INTERCOM: FeedbackKind.CONVERSATION,
    SourceType.TWITTER: FeedbackKind.POST,
    SourceType.DISCOURSE: FeedbackKind.POST,
}


class Tenant(FrozenModel):
    id: str
    name: str
    api_key_hash: str


class Source(FrozenModel):
    id: str
    tenant_id: str
    type: SourceType
    name: str
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


class FeedbackRecord(FrozenModel):
    id: str
    tenant_id: str
    source_id: str
    source_type: SourceType
    external_id: str
    kind: FeedbackKind
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

    @model_validator(mode="before")
    @classmethod
    def _kind_from_source_type(cls, data: object) -> object:
        if isinstance(data, dict) and "source_type" in data:
            return data | {"kind": KIND_BY_SOURCE[SourceType(data["source_type"])]}
        return data

    @model_validator(mode="after")
    def _source_type_agrees(self) -> Self:
        if self.metadata.source_type != self.source_type:
            msg = f"metadata is for {self.metadata.source_type}, record is {self.source_type}"
            raise ValueError(msg)
        return self

    @property
    def version_at(self) -> datetime:
        return self.source_updated_at or self.source_created_at
