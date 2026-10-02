from http import HTTPStatus

from fastapi import APIRouter, Response

from feedback_ingest.api.deps import Ctx
from feedback_ingest.api.schemas import HealthResponse

router = APIRouter()


@router.get("/health")
def health(ctx: Ctx, response: Response) -> HealthResponse:
    enabled, alive = ctx.settings.worker_enabled, ctx.worker.alive
    scheduler_enabled = ctx.settings.scheduler_enabled
    failing = sorted(ctx.scheduler.last_errors)
    degraded = (
        (enabled and not ctx.worker.healthy)
        or (scheduler_enabled and not ctx.scheduler.alive)
        or bool(failing)
    )
    if degraded:
        response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
    return HealthResponse(
        status="degraded" if degraded else "ok",
        worker_enabled=enabled,
        worker_alive=alive,
        scheduler_enabled=scheduler_enabled,
        scheduler_alive=ctx.scheduler.alive,
        failing_sources=failing,
        queue=ctx.adapters.queue.counts(),
    )
