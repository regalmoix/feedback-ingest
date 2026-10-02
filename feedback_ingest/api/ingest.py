import json
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from feedback_ingest.api.deps import Ctx, tenant_source
from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.errors import UnauthorizedError
from feedback_ingest.domain.models import Source
from feedback_ingest.services.ingestion import AcceptResult

router = APIRouter()


@router.post("/v1/sources/{source_id}/events", status_code=HTTPStatus.ACCEPTED)
async def ingest_event(
    request: Request, source: Annotated[Source, Depends(tenant_source)], ctx: Ctx
) -> AcceptResult:
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
    return await run_in_threadpool(ctx.ingestion.accept, source, payload)
