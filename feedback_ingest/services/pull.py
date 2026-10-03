import logging
import threading
from dataclasses import dataclass, field
from datetime import timedelta

from pydantic import NonNegativeInt

from feedback_ingest.connectors.registry import PULLERS
from feedback_ingest.domain.errors import ConflictError, PermanentError, TransientError
from feedback_ingest.domain.metadata import FrozenModel
from feedback_ingest.domain.models import Source
from feedback_ingest.ports.clock import Clock
from feedback_ingest.ports.http import HttpClient
from feedback_ingest.ports.stores import SourceStore
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.utils.time import NAIVE_UTC

log = logging.getLogger(__name__)


class PullResult(FrozenModel):
    source_id: str
    pages: NonNegativeInt = 0
    accepted: NonNegativeInt = 0
    duplicates: NonNegativeInt = 0
    cursor: str | None = None
    error: str | None = None


# ponytail: the per-source lock is per process; a second process (uvicorn --workers N) can still
# sync the same source at once (the unique raw-event key absorbs it). Use a DB lease if it matters.
@dataclass
class PullService:
    sources: SourceStore
    ingestion: IngestionService
    http: HttpClient
    clock: Clock
    deadline_seconds: float
    _running: dict[str, threading.Lock] = field(default_factory=dict, init=False, repr=False)

    def sync(self, source: Source) -> PullResult:
        lock = self._running.setdefault(source.id, threading.Lock())
        if not lock.acquire(blocking=False):
            msg = f"source {source.id} is already syncing"
            raise ConflictError(msg)
        try:
            return self._sync(source)
        finally:
            lock.release()

    def _sync(self, source: Source) -> PullResult:
        extra = {"tenant_id": source.tenant_id, "source_id": source.id}
        pages = accepted = duplicates = 0
        cursor = error = None
        deadline = self.clock.now() + timedelta(seconds=self.deadline_seconds)
        try:
            for page in PULLERS[source.type].pull(source, self.http, self.clock, deadline):
                # ponytail: whole-page accept loop; batch enqueue if a page ever holds thousands
                # of items
                for payload in page.payloads:
                    if self.ingestion.accept(source, payload).duplicate:
                        duplicates += 1
                    else:
                        accepted += 1
                cursor = self._advance(source, page.cursor)
                pages += 1
        except (TransientError, PermanentError) as exc:  # anything else is ours: let it raise
            log.warning("pull stopped at the saved cursor: %s", exc, exc_info=exc, extra=extra)
            error = str(exc)
        log.info("pulled %d pages: %d new, %d duplicates", pages, accepted, duplicates, extra=extra)
        return PullResult(
            source_id=source.id,
            pages=pages,
            accepted=accepted,
            duplicates=duplicates,
            cursor=cursor,
            error=error,
        )

    # ponytail: assumes every cursor is an ISO timestamp (true for Discourse); let the connector
    # compare cursors when one is not
    def _advance(self, source: Source, cursor: str) -> str:
        stored = self.sources.get(source.id, source.tenant_id)
        if stored is not None and stored.cursor is not None:
            cursor = max(stored.cursor, cursor, key=NAIVE_UTC.validate_python)
        self.sources.update_cursor(source.id, source.tenant_id, cursor)
        return cursor
