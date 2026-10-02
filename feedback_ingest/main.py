import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, nullcontext

from fastapi import FastAPI

from feedback_ingest.api import admin, health, ingest, records, sources, sync, tenants
from feedback_ingest.api.deps import Adapters, AppState
from feedback_ingest.api.errors import add_error_handlers
from feedback_ingest.config import Settings
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.services.pipeline import PipelineService
from feedback_ingest.services.pull import PullService
from feedback_ingest.services.scheduler import SchedulerService
from feedback_ingest.services.worker import WorkerService
from feedback_ingest.wiring import sql_adapters

_LOG = logging.getLogger("feedback_ingest")
_LOG_KEYS = ("raw_event_id", "tenant_id", "source_id", "attempts")


def create_app(settings: Settings | None = None, adapters: Adapters | None = None) -> FastAPI:
    s = settings or Settings()
    if not _LOG.handlers:
        handler = logging.StreamHandler()
        keys = " ".join(f"{key}=%({key})s" for key in _LOG_KEYS)
        fmt = f"%(asctime)s %(levelname)s %(name)s %(message)s {keys}"
        handler.setFormatter(logging.Formatter(fmt, defaults=dict.fromkeys(_LOG_KEYS, "-")))
        _LOG.addHandler(handler)
        _LOG.setLevel(logging.INFO)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        built = nullcontext(adapters) if adapters is not None else sql_adapters(s.database_url)
        with built as a:
            if not s.bootstrap_token:
                _LOG.warning("FI_BOOTSTRAP_TOKEN is empty; POST /admin/tenants is disabled")
            elif s.bootstrap_token == Settings.model_fields["bootstrap_token"].default:
                _LOG.warning(
                    "FI_BOOTSTRAP_TOKEN is the default; set it before exposing /admin/tenants"
                )
            pipeline = PipelineService(
                a.sources, a.feedback, a.queue, a.clock, s.max_attempts, s.backoff_cap_seconds
            )
            worker = WorkerService(
                a.queue, pipeline, a.clock, s.worker_poll_seconds, s.lease_seconds, s.claim_batch
            )
            ingestion = IngestionService(a.queue, a.clock)
            pull = PullService(a.sources, ingestion, a.http, a.clock)
            scheduler = SchedulerService(pull, s.pull_interval_seconds)
            app.state.ctx = AppState(s, a, ingestion, worker, pull, scheduler)
            if s.worker_enabled:
                worker.start()
            if s.scheduler_enabled:
                scheduler.start()
            try:
                yield
            finally:
                scheduler.stop()
                worker.stop()

    app = FastAPI(title="Feedback ingest", lifespan=lifespan)
    add_error_handlers(app)
    for module in (ingest, admin, health, sources, records, tenants, sync):
        app.include_router(module.router)
    return app


app = create_app()
