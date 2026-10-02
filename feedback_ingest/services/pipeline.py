import logging
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta

from pydantic import ValidationError

from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.enums import EventStatus, UpsertOutcome
from feedback_ingest.domain.errors import TransformError, TransientError
from feedback_ingest.domain.models import RawEvent
from feedback_ingest.ports.clock import Clock
from feedback_ingest.ports.queue import RawEventQueue
from feedback_ingest.ports.stores import FeedbackStore, SourceStore

log = logging.getLogger(__name__)
_MAX_ERROR = 500


def event_extra(event: RawEvent) -> dict[str, object]:
    return {
        "raw_event_id": event.id,
        "tenant_id": event.tenant_id,
        "source_id": event.source_id,
        "attempts": event.attempts,
    }


@dataclass
class PipelineService:
    sources: SourceStore
    feedback: FeedbackStore
    queue: RawEventQueue
    clock: Clock
    max_attempts: int
    backoff_cap_seconds: int

    def process(self, event: RawEvent) -> EventStatus:
        extra = event_extra(event)
        # a crash outside this handler leaves the lease to expire; each re-claim bumps attempts
        if event.attempts > self.max_attempts:
            last = event.error or "none recorded (worker crashed; see logs)"
            error = f"attempt limit exceeded; last error: {last}"[:_MAX_ERROR]
            log.warning("dead: %s", error, extra=extra)
            return _finish(self.queue.mark_dead(event, error), EventStatus.DEAD, extra)
        try:
            outcomes = self._apply(event)
        except (ValidationError, TransformError) as exc:
            error = _describe(exc)
            log.warning("dead: %s", error, extra=extra)
            return _finish(self.queue.mark_dead(event, error), EventStatus.DEAD, extra)
        except TransientError as exc:
            log.warning("transient failure: %s", exc, extra=extra)
            return self._retry(event, exc, extra)
        # ponytail: retries unknown exceptions too; classify more exceptions as permanent once we
        # see them in prod
        except Exception as exc:
            log.exception("unexpected failure", extra=extra)
            return self._retry(event, exc, extra)
        status = _finish(self.queue.mark_processed(event), EventStatus.PROCESSED, extra)
        if status == EventStatus.PROCESSED:
            counts = [outcomes[outcome] for outcome in UpsertOutcome]
            log.info("processed: inserted=%d, updated=%d, skipped_older=%d", *counts, extra=extra)
        return status

    def _apply(self, event: RawEvent) -> Counter[UpsertOutcome]:
        source = self.sources.get(event.source_id, tenant_id=event.tenant_id)
        if source is None:
            msg = "source not found"
            raise TransformError(msg)
        records = CONNECTORS[source.type].transform(source, dict(event.payload))
        now = self.clock.now()
        return Counter(
            self.feedback.upsert(r.model_copy(update={"ingested_at": now})) for r in records
        )

    def _retry(self, event: RawEvent, exc: Exception, extra: dict[str, object]) -> EventStatus:
        error = f"{type(exc).__name__}: {exc}"[:_MAX_ERROR]
        if event.attempts >= self.max_attempts:
            return _finish(self.queue.mark_dead(event, error), EventStatus.DEAD, extra)
        delay = min(2**event.attempts, self.backoff_cap_seconds)
        next_at = self.clock.now() + timedelta(seconds=delay)
        return _finish(self.queue.mark_failed(event, error, next_at), EventStatus.FAILED, extra)


def _describe(exc: ValidationError | TransformError) -> str:
    if isinstance(exc, TransformError):
        return str(exc)[:_MAX_ERROR]
    errors = exc.errors(include_url=False, include_input=False)  # no customer text in the error
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in errors)[:_MAX_ERROR]


def _finish(ok: bool, status: EventStatus, extra: dict[str, object]) -> EventStatus:
    if ok:
        return status
    log.warning("lease lost; a newer claim owns this event", extra=extra)
    return EventStatus.PROCESSING
