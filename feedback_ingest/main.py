import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, nullcontext
from typing import override

from fastapi import FastAPI

from feedback_ingest.api import admin, health, ingest, records, sources, sync, tenants
from feedback_ingest.api.deps import Adapters
from feedback_ingest.api.errors import add_error_handlers
from feedback_ingest.config import Settings
from feedback_ingest.wiring import app_state, sql_adapters

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


def _warn_about_bootstrap_token(token: str) -> None:
    if not token:
        _LOG.warning("FI_BOOTSTRAP_TOKEN is empty; POST /admin/tenants is disabled")
    elif token == Settings.model_fields["bootstrap_token"].default:
        _LOG.warning("FI_BOOTSTRAP_TOKEN is the default; set it before exposing /admin/tenants")


def create_app(settings: Settings | None = None, adapters: Adapters | None = None) -> FastAPI:
    settings = settings or Settings()
    _configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        built = (
            nullcontext(adapters) if adapters is not None else sql_adapters(settings.database_url)
        )
        with built as active:
            ctx = app_state(settings, active)
            _warn_about_bootstrap_token(settings.bootstrap_token)
            app.state.ctx = ctx
            if settings.worker_enabled:
                ctx.worker.start()
            if settings.scheduler_enabled:
                ctx.scheduler.start()
            try:
                yield
            finally:
                ctx.scheduler.stop()
                ctx.worker.stop()

    app = FastAPI(title="Feedback ingest", lifespan=lifespan)
    add_error_handlers(app)
    for module in (ingest, admin, health, sources, records, tenants, sync):
        app.include_router(module.router)
    return app


app = create_app()
