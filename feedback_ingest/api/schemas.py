from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from feedback_ingest.domain.enums import EventStatus, FeedbackKind, SourceMode, SourceType
from feedback_ingest.domain.models import Name
from feedback_ingest.utils.time import NaiveUtc


class RawEventView(BaseModel):
    id: str
    source_id: str
    status: EventStatus
    attempts: int
    error: str | None
    received_at: datetime
    next_attempt_at: datetime


class RawEventDetail(RawEventView):
    payload: dict[str, Any]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    worker_enabled: bool
    worker_alive: bool
    scheduler_enabled: bool
    scheduler_alive: bool
    failing_sources: int  # pull sources whose latest scheduled sync failed; no ids, no auth here
    queue: dict[EventStatus, int]


class SourceCreate(BaseModel):
    type: SourceType
    name: Name
    mode: SourceMode
    config: dict[str, str] = Field(default_factory=dict)
    webhook_secret: Annotated[str, StringConstraints(min_length=16)] | None = None

    @model_validator(mode="after")
    def _webhooks_are_push_only(self) -> Self:
        if self.mode is SourceMode.PULL and self.webhook_secret is not None:
            msg = "a pull source takes no webhook_secret: webhooks are push-only"
            raise ValueError(msg)
        return self


class SourceCreated(SourceCreate):
    id: str


class SourceView(BaseModel):
    id: str
    type: SourceType
    name: str
    mode: SourceMode
    config: dict[str, str]
    webhook_secret: Literal["***"] | None
    cursor: str | None
    enabled: bool


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    config: dict[str, str] | None = None  # merged key by key into the stored config


class RecordQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str | None = None
    kind: FeedbackKind | None = None
    since: NaiveUtc | None = None
    limit: int = Field(default=100, ge=1, le=500)
    include_deleted: bool = False


class TenantCreate(BaseModel):
    name: Name


class TenantCreated(BaseModel):
    id: str
    name: str
    api_key: str
