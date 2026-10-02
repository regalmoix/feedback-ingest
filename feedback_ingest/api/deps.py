from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request

from feedback_ingest.config import Settings
from feedback_ingest.domain.errors import NotFoundError, UnauthorizedError
from feedback_ingest.domain.models import Source, Tenant
from feedback_ingest.ports.clock import Clock
from feedback_ingest.ports.http import HttpClient
from feedback_ingest.ports.queue import RawEventQueue
from feedback_ingest.ports.stores import FeedbackStore, SourceStore, TenantStore
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.services.worker import WorkerService
from feedback_ingest.utils.hashing import sha256_text


@dataclass(frozen=True)
class Adapters:
    tenants: TenantStore
    sources: SourceStore
    feedback: FeedbackStore
    queue: RawEventQueue
    http: HttpClient
    clock: Clock


@dataclass(frozen=True)
class AppState:
    settings: Settings
    adapters: Adapters
    ingestion: IngestionService
    worker: WorkerService


def get_ctx(request: Request) -> AppState:
    ctx: AppState = request.app.state.ctx
    return ctx


Ctx = Annotated[AppState, Depends(get_ctx)]


def current_tenant(ctx: Ctx, x_api_key: Annotated[str, Header(alias="X-API-Key")] = "") -> Tenant:
    tenant = ctx.adapters.tenants.get_by_api_key_hash(sha256_text(x_api_key)) if x_api_key else None
    if tenant is None:
        msg = "missing or unknown X-API-Key"
        raise UnauthorizedError(msg)
    return tenant


CurrentTenant = Annotated[Tenant, Depends(current_tenant)]


def tenant_source(source_id: str, tenant: CurrentTenant, ctx: Ctx) -> Source:
    source = ctx.adapters.sources.get(source_id, tenant_id=tenant.id)
    if source is None:
        msg = f"source {source_id} not found"
        raise NotFoundError(msg)
    return source
