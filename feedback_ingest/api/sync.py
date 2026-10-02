from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from feedback_ingest.api.deps import Ctx, tenant_source
from feedback_ingest.domain.enums import SourceMode
from feedback_ingest.domain.models import Source
from feedback_ingest.services.pull import PullResult

router = APIRouter()


# ponytail: inline sync; enqueue a "sync job" if a backfill takes minutes
@router.post("/v1/sources/{source_id}/sync")
def sync_source(
    source: Annotated[Source, Depends(tenant_source)], ctx: Ctx, response: Response
) -> PullResult:
    if source.mode is not SourceMode.PULL or not source.enabled:
        detail = f"source {source.id} is not an enabled pull source"
        raise HTTPException(HTTPStatus.CONFLICT, detail=detail)
    result = ctx.pull.sync(source)
    if result.error is not None:
        response.status_code = HTTPStatus.BAD_GATEWAY
    return result
