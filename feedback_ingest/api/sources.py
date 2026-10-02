import secrets
from http import HTTPStatus
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from feedback_ingest.api.deps import Ctx, CurrentTenant, tenant_source
from feedback_ingest.api.schemas import SourceCreate, SourceCreated, SourceUpdate, SourceView
from feedback_ingest.connectors.registry import check_source
from feedback_ingest.domain.enums import SourceMode
from feedback_ingest.domain.models import Source

router = APIRouter(prefix="/v1/sources")


@router.post("", status_code=HTTPStatus.CREATED)
def create_source(body: SourceCreate, tenant: CurrentTenant, ctx: Ctx) -> SourceCreated:
    secret = body.webhook_secret
    if body.mode is SourceMode.PUSH and not secret:
        secret = secrets.token_hex(32)
    source = Source(
        id=uuid4().hex,
        tenant_id=tenant.id,
        type=body.type,
        name=body.name,
        mode=body.mode,
        config=body.config,
        webhook_secret=secret,
        cursor=None,
    )
    try:
        check_source(source)
    except ValueError as exc:
        raise HTTPException(HTTPStatus.UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    ctx.adapters.sources.add(source)
    return SourceCreated.model_validate(
        body.model_dump() | {"id": source.id, "webhook_secret": secret}
    )


@router.get("")
def list_sources(tenant: CurrentTenant, ctx: Ctx) -> list[SourceView]:
    return [_view(source) for source in ctx.adapters.sources.list_for_tenant(tenant.id)]


@router.get("/{source_id}")
def get_source(source: Annotated[Source, Depends(tenant_source)]) -> SourceView:
    return _view(source)


@router.patch("/{source_id}")
def update_source(
    body: SourceUpdate, source: Annotated[Source, Depends(tenant_source)], ctx: Ctx
) -> SourceView:
    ctx.adapters.sources.set_enabled(source.id, source.tenant_id, body.enabled)
    return _view(source.model_copy(update={"enabled": body.enabled}))


def _view(source: Source) -> SourceView:
    masked = "***" if source.webhook_secret else None
    return SourceView.model_validate(source.model_dump() | {"webhook_secret": masked})
