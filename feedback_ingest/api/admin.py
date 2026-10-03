from typing import Annotated, Literal

from fastapi import APIRouter, Query

from feedback_ingest.api.deps import Ctx, CurrentTenant
from feedback_ingest.api.schemas import RawEventDetail, RawEventView
from feedback_ingest.domain.enums import EventStatus
from feedback_ingest.domain.errors import ConflictError, NotFoundError
from feedback_ingest.domain.models import RawEvent, Tenant

router = APIRouter(prefix="/admin")
Limit = Annotated[int, Query(ge=1, le=500)]


@router.get("/raw-events", response_model=list[RawEventView])
def list_raw_events(
    tenant: CurrentTenant, ctx: Ctx, status: EventStatus = EventStatus.DEAD, limit: Limit = 50
) -> list[RawEvent]:
    return ctx.adapters.queue.list_by_status(status, tenant_id=tenant.id, limit=limit)


@router.post("/raw-events/replay")
def replay_raw_events(
    tenant: CurrentTenant,
    ctx: Ctx,
    source_id: str | None = None,
    status: Literal["dead", "failed", "processed"] = "dead",
    limit: Limit = 500,
) -> dict[str, int]:
    queue, now = ctx.adapters.queue, ctx.adapters.clock.now()
    if source_id is not None and ctx.adapters.sources.get(source_id, tenant_id=tenant.id) is None:
        msg = f"source {source_id} not found"
        raise NotFoundError(msg)
    events = queue.list_by_status(
        EventStatus(status), tenant_id=tenant.id, source_id=source_id, limit=limit
    )
    return {"replayed": sum(queue.replay(event.id, now) for event in events)}


@router.get("/raw-events/{event_id}", response_model=RawEventDetail)
def get_raw_event(event_id: str, tenant: CurrentTenant, ctx: Ctx) -> RawEvent:
    return _tenant_event(event_id, tenant, ctx)


@router.post("/raw-events/{event_id}/replay")
def replay_raw_event(event_id: str, tenant: CurrentTenant, ctx: Ctx) -> dict[str, EventStatus]:
    _tenant_event(event_id, tenant, ctx)
    if not ctx.adapters.queue.replay(event_id, ctx.adapters.clock.now()):
        msg = "event is being processed"
        raise ConflictError(msg)
    return {"status": EventStatus.PENDING}


@router.get("/queue")
def queue_counts(tenant: CurrentTenant, ctx: Ctx) -> dict[EventStatus, int]:
    return ctx.adapters.queue.counts(tenant_id=tenant.id)


def _tenant_event(event_id: str, tenant: Tenant, ctx: Ctx) -> RawEvent:
    event = ctx.adapters.queue.get(event_id)
    if event is None or event.tenant_id != tenant.id:
        msg = f"raw event {event_id} not found"
        raise NotFoundError(msg)
    return event
