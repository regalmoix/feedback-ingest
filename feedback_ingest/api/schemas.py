from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from feedback_ingest.domain.enums import EventStatus


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
    queue: dict[EventStatus, int]
