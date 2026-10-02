import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from feedback_ingest.ports.clock import Clock
from feedback_ingest.ports.queue import RawEventQueue
from feedback_ingest.services.pipeline import PipelineService

log = logging.getLogger(__name__)


# ponytail: one thread, one process; uvicorn --workers N would start N of these, which is safe
# because the claim is atomic, but set FI_WORKER_ENABLED=false on all but one if you want a
# single consumer
@dataclass
class WorkerService:
    queue: RawEventQueue
    pipeline: PipelineService
    clock: Clock
    poll_seconds: float
    lease_seconds: int
    batch: int
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _last_ok_at: datetime | None = field(default=None, init=False, repr=False)

    def run_once(self) -> int:
        events = self.queue.claim(self.clock.now(), self.lease_seconds, self.batch)
        for event in events:
            try:
                self.pipeline.process(event)
            except Exception:
                extra = {
                    "raw_event_id": event.id,
                    "tenant_id": event.tenant_id,
                    "source_id": event.source_id,
                    "attempts": event.attempts,
                }
                log.exception("process crashed", extra=extra)
        self._last_ok_at = self.clock.now()
        return len(events)

    def start(self) -> None:
        self._last_ok_at = self.clock.now()
        self._thread = threading.Thread(target=self._loop, name="feedback-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.lease_seconds)
            if self._thread.is_alive():
                log.warning("worker still busy on stop; its batch is reclaimed after the lease")

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def healthy(self) -> bool:
        last, window = self._last_ok_at, timedelta(seconds=max(3 * self.poll_seconds, 10))
        return self.alive and last is not None and self.clock.now() - last <= window

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                busy = self.run_once() > 0
            except Exception:
                log.exception("worker iteration failed")
                busy = False
            if not busy:
                self._stop.wait(self.poll_seconds)
