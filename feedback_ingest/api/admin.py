from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from feedback_ingest.api.deps import Ctx, CurrentTenant
from feedback_ingest.api.schemas import RawEventView, ReplayResponse
from feedback_ingest.domain.enums import EventStatus
from feedback_ingest.domain.errors import NotFoundError
from feedback_ingest.domain.models import RawEvent, Tenant

router = APIRouter(prefix="/admin")


@router.get("/raw-events", response_model=list[RawEventView])
def list_raw_events(
    tenant: CurrentTenant,
    ctx: Ctx,
    status: EventStatus = EventStatus.DEAD,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[RawEvent]:
    return ctx.adapters.queue.list_by_status(status, tenant_id=tenant.id, limit=limit)


@router.get("/raw-events/{event_id}")
def get_raw_event(event_id: str, tenant: CurrentTenant, ctx: Ctx) -> RawEvent:
    return _tenant_event(event_id, tenant, ctx)


@router.post("/raw-events/{event_id}/replay")
def replay_raw_event(event_id: str, tenant: CurrentTenant, ctx: Ctx) -> ReplayResponse:
    _tenant_event(event_id, tenant, ctx)
    if not ctx.adapters.queue.requeue(event_id, ctx.adapters.clock.now()):
        raise HTTPException(HTTPStatus.CONFLICT, detail="event is being processed")
    return ReplayResponse(status=EventStatus.PENDING)


@router.get("/queue")
def queue_counts(tenant: CurrentTenant, ctx: Ctx) -> dict[EventStatus, int]:
    return ctx.adapters.queue.counts(tenant_id=tenant.id)


def _tenant_event(event_id: str, tenant: Tenant, ctx: Ctx) -> RawEvent:
    event = ctx.adapters.queue.get(event_id)
    if event is None or event.tenant_id != tenant.id:
        msg = f"raw event {event_id} not found"
        raise NotFoundError(msg)
    return event
