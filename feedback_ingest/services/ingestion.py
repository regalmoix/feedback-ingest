import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.models import RawEvent, Source
from feedback_ingest.ports.clock import Clock
from feedback_ingest.ports.queue import RawEventQueue

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AcceptResult:
    raw_event_id: str  # the stored row's id, also on a duplicate
    duplicate: bool


@dataclass
class IngestionService:
    queue: RawEventQueue
    clock: Clock

    def accept(self, source: Source, payload: Mapping[str, Any]) -> AcceptResult:
        now = self.clock.now()
        event = RawEvent(
            id=uuid4().hex,
            tenant_id=source.tenant_id,
            source_id=source.id,
            external_event_id=CONNECTORS[source.type].external_event_id(dict(payload)),
            payload=payload,
            received_at=now,
            next_attempt_at=now,
        )
        stored_id = self.queue.enqueue(event)
        result = AcceptResult(raw_event_id=stored_id, duplicate=stored_id != event.id)
        extra = {
            "raw_event_id": stored_id,
            "tenant_id": source.tenant_id,
            "source_id": source.id,
            "duplicate": result.duplicate,
        }
        log.info("accepted (duplicate=%s)", result.duplicate, extra=extra)
        return result
