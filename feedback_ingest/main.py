import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import override

from fastapi import FastAPI
from sqlalchemy import Engine

from feedback_ingest.adapters.http.httpx_client import HttpxClient
from feedback_ingest.adapters.sqlalchemy.db import make_engine
from feedback_ingest.adapters.sqlalchemy.raw_event_queue import SqlRawEventQueue
from feedback_ingest.adapters.sqlalchemy.stores import (
    SqlFeedbackStore,
    SqlSourceStore,
    SqlTenantStore,
)
from feedback_ingest.adapters.sqlalchemy.tables import Base
from feedback_ingest.api import admin, health, ingest, records, sources, tenants
from feedback_ingest.api.deps import Adapters, AppState
from feedback_ingest.api.errors import add_error_handlers
from feedback_ingest.config import Settings
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.services.pipeline import PipelineService
from feedback_ingest.services.worker import WorkerService
from feedback_ingest.utils.time import SystemClock

_LOG = logging.getLogger("feedback_ingest")
_LOG_KEYS = ("raw_event_id", "tenant_id", "source_id", "attempts")


class _DefaultLogKeys(logging.Filter):
    @override
    def filter(self, record: logging.LogRecord) -> bool:
        for key in _LOG_KEYS:
            if not hasattr(record, key):
                setattr(record, key, "-")
        return True


def _configure_logging() -> None:
    logger = logging.getLogger("feedback_ingest")
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.addFilter(_DefaultLogKeys())
    keys = " ".join(f"{key}=%({key})s" for key in _LOG_KEYS)
    handler.setFormatter(
        logging.Formatter(f"%(asctime)s %(levelname)s %(name)s %(message)s {keys}")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _sql_adapters(engine: Engine) -> Adapters:
    return Adapters(
        tenants=SqlTenantStore(engine),
        sources=SqlSourceStore(engine),
        feedback=SqlFeedbackStore(engine),
        queue=SqlRawEventQueue(engine),
        http=HttpxClient(),
        clock=SystemClock(),
    )


def _app_state(settings: Settings, a: Adapters) -> AppState:
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
    return AppState(settings, a, IngestionService(a.queue, a.clock), worker)


def create_app(settings: Settings | None = None, adapters: Adapters | None = None) -> FastAPI:
    settings = settings or Settings()
    _configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = None
        active = adapters
        if active is None:
            engine = make_engine(settings.database_url)
            Base.metadata.create_all(engine)
            active = _sql_adapters(engine)
        ctx = _app_state(settings, active)
        if settings.bootstrap_token == Settings.model_fields["bootstrap_token"].default:
            _LOG.warning("FI_BOOTSTRAP_TOKEN is the default; set it before exposing /admin/tenants")
        app.state.ctx = ctx
        if settings.worker_enabled:
            ctx.worker.start()
        try:
            yield
        finally:
            ctx.worker.stop()
            if engine is not None:
                engine.dispose()

    app = FastAPI(title="Feedback ingest", lifespan=lifespan)
    add_error_handlers(app)
    for module in (ingest, admin, health, sources, records, tenants):
        app.include_router(module.router)
    return app


app = create_app()
