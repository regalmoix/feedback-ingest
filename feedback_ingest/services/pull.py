import logging
from dataclasses import dataclass

from pydantic import BaseModel

from feedback_ingest.connectors.registry import PULLERS
from feedback_ingest.domain.enums import SourceMode
from feedback_ingest.domain.errors import TransientError
from feedback_ingest.domain.models import Source
from feedback_ingest.ports.clock import Clock
from feedback_ingest.ports.http import HttpClient
from feedback_ingest.ports.stores import SourceStore
from feedback_ingest.services.ingestion import IngestionService

log = logging.getLogger(__name__)


class ConfigError(Exception):
    pass


class PullResult(BaseModel):
    source_id: str
    pages: int
    accepted: int
    duplicates: int
    cursor: str | None
    error: str | None


# ponytail: no per-source lock; a manual sync racing the scheduler fetches twice and the last
# cursor write wins, which the unique raw-event key absorbs
@dataclass
class PullService:
    sources: SourceStore
    ingestion: IngestionService
    http: HttpClient
    clock: Clock

    def sync(self, source: Source) -> PullResult:
        puller = PULLERS.get(source.type)
        if puller is None:
            msg = f"{source.type} sources are push-only; there is nothing to sync"
            raise ConfigError(msg)
        extra = {"tenant_id": source.tenant_id, "source_id": source.id}
        pages = accepted = duplicates = 0
        cursor = error = None
        try:
            for page in puller.pull(source, self.http, self.clock.now()):
                # ponytail: whole-page accept loop; batch enqueue if a page ever holds thousands
                # of items
                for payload in page.payloads:
                    if self.ingestion.accept(source, payload).duplicate:
                        duplicates += 1
                    else:
                        accepted += 1
                self.sources.update_cursor(source.id, page.cursor)
                pages, cursor = pages + 1, page.cursor
        except TransientError as exc:
            log.warning("pull stopped, will resume next tick: %s", exc, extra=extra)
            error = f"TransientError: {exc}"
        except Exception as exc:
            log.exception("pull failed", extra=extra)
            error = f"{type(exc).__name__}: {exc}"
        log.info("pulled %d pages: %d new, %d duplicates", pages, accepted, duplicates, extra=extra)
        return PullResult(
            source_id=source.id,
            pages=pages,
            accepted=accepted,
            duplicates=duplicates,
            cursor=cursor,
            error=error,
        )

    def sync_all(self) -> list[PullResult]:
        return [self.sync(source) for source in self.sources.list_by_mode(SourceMode.PULL)]
