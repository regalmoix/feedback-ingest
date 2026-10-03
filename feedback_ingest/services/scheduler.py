import logging
import threading
from dataclasses import dataclass, field

from feedback_ingest.domain.enums import SourceMode
from feedback_ingest.domain.errors import ConflictError
from feedback_ingest.domain.models import Source
from feedback_ingest.services.pull import PullService

log = logging.getLogger(__name__)
_JOIN_SECONDS = (
    5  # short so shutdown is quick; an abandoned sync resumes from its saved page cursor
)


# ponytail: one thread ticks every pull source in turn; a slow source delays the rest of the tick,
# move to a pool per source if tenants grow
@dataclass
class SchedulerService:
    pull: PullService
    interval_seconds: float
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    failing_sources: int = field(default=0, init=False)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="pull-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=_JOIN_SECONDS)
            if self._thread.is_alive():
                log.warning("scheduler still syncing on stop; it resumes from the saved cursor")

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        sources: list[Source] = []
        while not self._stop.wait(self.interval_seconds):
            try:
                sources = self.pull.sources.list_enabled(SourceMode.PULL)
                failing = sum(self._sync_one(source) for source in sources)
            except Exception:
                log.exception("scheduler tick failed")
                failing = max(len(sources), 1)  # every source last listed; never 0 on a broken tick
            self.failing_sources = failing  # health shows this tick only

    def _sync_one(self, source: Source) -> bool:
        extra = {"tenant_id": source.tenant_id, "source_id": source.id}
        try:
            return self.pull.sync(source).error is not None
        except ConflictError:
            log.info("skipped: a manual sync is running", extra=extra)
            return False
        except Exception:  # one broken source must not starve the rest of the tick
            if self._stop.is_set():
                log.info("sync abandoned at shutdown", extra=extra)
            else:
                log.exception("scheduled sync failed", extra=extra)
            return True
