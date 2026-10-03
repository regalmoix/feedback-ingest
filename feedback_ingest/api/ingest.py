import json
from collections.abc import Mapping
from http import HTTPStatus

from fastapi import APIRouter, HTTPException, Request
from pydantic_core import to_json
from starlette.concurrency import run_in_threadpool

from feedback_ingest.api.deps import AppState, Ctx
from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.enums import SourceMode
from feedback_ingest.domain.errors import ConflictError, NotFoundError, UnauthorizedError
from feedback_ingest.services.ingestion import AcceptResult

router = APIRouter()


# No API key: a real sender cannot add one. The unguessable source id picks the source and its
# per-source signature proves the caller; the tenant comes from the source row.
@router.post("/v1/sources/{source_id}/events", status_code=HTTPStatus.ACCEPTED)
async def ingest_event(source_id: str, request: Request, ctx: Ctx) -> AcceptResult:
    body = await request.body()
    return await run_in_threadpool(_ingest, ctx, source_id, body, request.headers)


def _ingest(ctx: AppState, source_id: str, body: bytes, headers: Mapping[str, str]) -> AcceptResult:
    source = ctx.adapters.sources.get_by_id(source_id)
    if source is None:
        msg = f"source {source_id} not found"
        raise NotFoundError(msg)
    secret = source.webhook_secret if source.mode is SourceMode.PUSH else None
    if secret is None:
        msg = "source does not accept webhooks"
        raise ConflictError(msg)
    if not CONNECTORS[source.type].verify_signature(secret.get_secret_value(), body, headers):
        msg = "bad or missing signature"
        raise UnauthorizedError(msg)
    if not source.enabled:  # after the signature: state is only told to a caller who proved itself
        msg = "source is disabled"
        raise ConflictError(msg)
    try:
        payload = json.loads(body, parse_constant=_not_json)
        to_json(payload)  # nesting json.loads accepts but storage and validation would not
    except (ValueError, RecursionError):  # PydanticSerializationError is a ValueError
        payload = None
    if not isinstance(payload, dict):
        raise HTTPException(HTTPStatus.BAD_REQUEST, detail="body must be a JSON object")
    return ctx.ingestion.accept(source, payload)


def _not_json(constant: str) -> None:
    msg = f"{constant} is not JSON"
    raise ValueError(msg)
