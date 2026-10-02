from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from feedback_ingest.api.deps import Ctx, tenant_source
from feedback_ingest.domain.enums import SourceMode
from feedback_ingest.domain.models import Source
from feedback_ingest.services.pull import ConfigError, PullResult

router = APIRouter()


# ponytail: inline sync; enqueue a "sync job" if a backfill takes minutes
@router.post("/v1/sources/{source_id}/sync")
def sync_source(source: Annotated[Source, Depends(tenant_source)], ctx: Ctx) -> PullResult:
    if source.mode is not SourceMode.PULL or not source.enabled:
        detail = f"source {source.id} is not an enabled pull source"
        raise HTTPException(HTTPStatus.CONFLICT, detail=detail)
    try:
        return ctx.pull.sync(source)
    except ConfigError as exc:
        raise HTTPException(HTTPStatus.CONFLICT, detail=str(exc)) from exc
