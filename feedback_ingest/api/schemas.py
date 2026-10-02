from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from feedback_ingest.domain.enums import EventStatus, FeedbackKind, SourceMode, SourceType
from feedback_ingest.utils.time import NaiveUtc


class RawEventView(BaseModel):
    id: str
    source_id: str
    status: EventStatus
    attempts: int
    error: str | None
    received_at: datetime
    next_attempt_at: datetime


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
    name: str
    mode: SourceMode
    config: dict[str, str] = Field(default_factory=dict)
    webhook_secret: str | None = None


class SourceCreated(SourceCreate):
    id: str


class SourceView(SourceCreated):
    webhook_secret: Literal["***"] | None
    cursor: str | None
    enabled: bool


class SourceUpdate(BaseModel):
    enabled: bool


class RecordQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str | None = None
    kind: FeedbackKind | None = None
    since: NaiveUtc | None = None
    limit: int = Field(default=100, ge=1, le=500)
    include_deleted: bool = False


class TenantCreate(BaseModel):
    name: str = Field(min_length=1)


class TenantCreated(BaseModel):
    id: str
    name: str
    api_key: str
