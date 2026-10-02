from collections.abc import Iterator
from contextlib import contextmanager

from feedback_ingest.adapters.http.httpx_client import HttpxClient
from feedback_ingest.adapters.sqlalchemy.db import assert_schema_matches, make_engine
from feedback_ingest.adapters.sqlalchemy.feedback_store import SqlFeedbackStore
from feedback_ingest.adapters.sqlalchemy.raw_event_queue import SqlRawEventQueue
from feedback_ingest.adapters.sqlalchemy.stores import SqlSourceStore, SqlTenantStore
from feedback_ingest.adapters.sqlalchemy.tables import Base
from feedback_ingest.api.deps import Adapters, AppState
from feedback_ingest.config import Settings
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.services.pipeline import PipelineService
from feedback_ingest.services.pull import PullService
from feedback_ingest.services.scheduler import SchedulerService
from feedback_ingest.services.worker import WorkerService
from feedback_ingest.utils.time import SystemClock


@contextmanager
def sql_adapters(database_url: str) -> Iterator[Adapters]:
    engine = make_engine(database_url)
    http = HttpxClient()
    try:
        Base.metadata.create_all(engine)
        assert_schema_matches(engine)
        yield Adapters(
            tenants=SqlTenantStore(engine),
            sources=SqlSourceStore(engine),
            feedback=SqlFeedbackStore(engine),
            queue=SqlRawEventQueue(engine),
            http=http,
            clock=SystemClock(),
        )
    finally:
        http.close()
        engine.dispose()


def app_state(settings: Settings, a: Adapters) -> AppState:
    pipeline = PipelineService(
        a.sources, a.feedback, a.queue, a.clock, settings.max_attempts, settings.backoff_cap_seconds
    )
    worker = WorkerService(
        a.queue,
        pipeline,
        a.clock,
        settings.worker_poll_seconds,
        settings.lease_seconds,
        settings.claim_batch,
    )
    ingestion = IngestionService(a.queue, a.clock)
    pull = PullService(a.sources, ingestion, a.http, a.clock)
    scheduler = SchedulerService(pull, settings.pull_interval_seconds)
    return AppState(settings, a, ingestion, worker, pull, scheduler)
