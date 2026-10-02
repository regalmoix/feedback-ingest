import logging
import threading
from dataclasses import dataclass, field

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

    def run_once(self) -> int:
        events = self.queue.claim(self.clock.now(), self.lease_seconds, self.batch)
        for event in events:
            self.pipeline.process(event)
        return len(events)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="feedback-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.lease_seconds)  # past the lease the batch is reclaimed

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ponytail: a crash mid-batch leaves the rest of that batch leased until lease_seconds pass
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                busy = self.run_once() > 0
            except Exception:
                log.exception("worker iteration failed")
                busy = False
            if not busy:
                self._stop.wait(self.poll_seconds)
