from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from feedback_ingest.domain.enums import EventStatus, FeedbackKind, SourceMode, SourceType


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
    scheduler_alive: bool
    queue: dict[EventStatus, int]


class SourceCreate(BaseModel):
    type: SourceType
    name: str
    mode: SourceMode
    config: dict[str, str] = Field(default_factory=dict)
    webhook_secret: str | None = None


class SourceCreated(BaseModel):
    id: str
    type: SourceType
    name: str
    mode: SourceMode
    config: dict[str, str]
    webhook_secret: str | None


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
    enabled: bool


class RecordQuery(BaseModel):
    source_id: str | None = None
    kind: FeedbackKind | None = None
    since: datetime | None = None
    limit: int = Field(default=100, ge=1, le=500)
    include_deleted: bool = False


class TenantCreate(BaseModel):
    name: str


class TenantCreated(BaseModel):
    id: str
    name: str
    api_key: str
