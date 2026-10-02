import json
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from feedback_ingest.api.deps import Ctx, tenant_source
from feedback_ingest.api.schemas import AcceptResponse
from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.errors import UnauthorizedError
from feedback_ingest.domain.models import Source

router = APIRouter()


# ponytail: sync DB call inside async handler; move to run_in_threadpool if p99 matters
@router.post("/v1/sources/{source_id}/events", status_code=HTTPStatus.ACCEPTED)
async def ingest_event(
    request: Request, source: Annotated[Source, Depends(tenant_source)], ctx: Ctx
) -> AcceptResponse:
    body = await request.body()
    secret = source.webhook_secret
    connector = CONNECTORS[source.type]
    if secret is None or not connector.verify_signature(
        secret.get_secret_value(), body, request.headers
    ):
        msg = "bad or missing signature"
        raise UnauthorizedError(msg)
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        payload = None
    if not isinstance(payload, dict):
        raise HTTPException(HTTPStatus.BAD_REQUEST, detail="body must be a JSON object")
    result = ctx.ingestion.accept(source, payload)
    return AcceptResponse(raw_event_id=result.raw_event_id, duplicate=result.duplicate)
