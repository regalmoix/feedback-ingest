import json
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from feedback_ingest.api.deps import Ctx
from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.errors import NotFoundError, UnauthorizedError
from feedback_ingest.domain.models import Source
from feedback_ingest.services.ingestion import AcceptResult

router = APIRouter()


def _webhook_source(source_id: str, ctx: Ctx) -> Source:
    source = ctx.adapters.sources.get_by_id(source_id)
    if source is None:
        msg = f"source {source_id} not found"
        raise NotFoundError(msg)
    return source


# No API key: a real sender cannot add one. The unguessable source id picks the source and its
# per-source signature proves the caller; the tenant comes from the source row.
@router.post("/v1/sources/{source_id}/events", status_code=HTTPStatus.ACCEPTED)
async def ingest_event(
    request: Request, source: Annotated[Source, Depends(_webhook_source)], ctx: Ctx
) -> AcceptResult:
    if not source.enabled:
        raise HTTPException(HTTPStatus.CONFLICT, detail="source is disabled")
    if source.webhook_secret is None:
        raise HTTPException(HTTPStatus.CONFLICT, detail="source has no webhook secret")
    body = await request.body()
    secret = source.webhook_secret.get_secret_value()
    if not CONNECTORS[source.type].verify_signature(secret, body, request.headers):
        msg = "bad or missing signature"
        raise UnauthorizedError(msg)
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        payload = None
    if not isinstance(payload, dict):
        raise HTTPException(HTTPStatus.BAD_REQUEST, detail="body must be a JSON object")
    return await run_in_threadpool(ctx.ingestion.accept, source, payload)
