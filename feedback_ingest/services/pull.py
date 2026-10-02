import logging
from dataclasses import dataclass

from pydantic import BaseModel

from feedback_ingest.connectors.registry import PULLERS
from feedback_ingest.domain.errors import TransformError, TransientError
from feedback_ingest.domain.models import Source
from feedback_ingest.ports.clock import Clock
from feedback_ingest.ports.http import HttpClient
from feedback_ingest.ports.stores import SourceStore
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.utils.time import NAIVE_UTC

log = logging.getLogger(__name__)


class PullResult(BaseModel):
    source_id: str
    pages: int = 0
    accepted: int = 0
    duplicates: int = 0
    cursor: str | None = None
    error: str | None = None


# ponytail: no per-source lock; a manual sync racing the scheduler fetches twice (the unique
# raw-event key absorbs it) and the read-then-write cursor max can lose that race; lock per source
# if it matters
@dataclass
class PullService:
    sources: SourceStore
    ingestion: IngestionService
    http: HttpClient
    clock: Clock

    def sync(self, source: Source) -> PullResult:
        extra = {"tenant_id": source.tenant_id, "source_id": source.id}
        pages = accepted = duplicates = 0
        cursor = error = None
        try:
            for page in PULLERS[source.type].pull(source, self.http, self.clock.now()):
                # ponytail: whole-page accept loop; batch enqueue if a page ever holds thousands
                # of items
                for payload in page.payloads:
                    if self.ingestion.accept(source, payload).duplicate:
                        duplicates += 1
                    else:
                        accepted += 1
                cursor = self._advance(source, page.cursor)
                pages += 1
        except (TransientError, TransformError) as exc:  # anything else is ours: let it raise
            log.warning("pull stopped at the saved cursor: %s", exc, extra=extra)
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
        self.sources.update_cursor(source.id, cursor)
        return cursor
