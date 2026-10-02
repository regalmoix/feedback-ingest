import logging
import threading
from dataclasses import dataclass, field

from feedback_ingest.services.pull import PullResult, PullService

log = logging.getLogger(__name__)
_JOIN_SECONDS = 5  # a sync abandoned mid-run resumes from its last saved page cursor


# ponytail: one thread ticks every pull source in turn; a slow source delays the rest of the tick,
# move to a pool per source if tenants grow
@dataclass
class SchedulerService:
    pull: PullService
    interval_seconds: float
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)

    def run_once(self) -> list[PullResult]:
        return self.pull.sync_all()

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
        while not self._stop.wait(self.interval_seconds):
            try:
                self.run_once()
            except Exception:
                log.exception("scheduler tick failed")
