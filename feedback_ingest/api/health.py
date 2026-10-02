from http import HTTPStatus

from fastapi import APIRouter, Response

from feedback_ingest.api.deps import Ctx
from feedback_ingest.api.schemas import HealthResponse

router = APIRouter()


@router.get("/health")
def health(ctx: Ctx, response: Response) -> HealthResponse:
    enabled, alive = ctx.settings.worker_enabled, ctx.worker.alive
    degraded = enabled and not alive
    if degraded:
        response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
    return HealthResponse(
        status="degraded" if degraded else "ok",
        worker_enabled=enabled,
        worker_alive=alive,
        scheduler_alive=ctx.scheduler.alive,
        queue=ctx.adapters.queue.counts(),
    )
