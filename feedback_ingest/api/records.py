from typing import Annotated

from fastapi import APIRouter, Query

from feedback_ingest.api.deps import Ctx, CurrentTenant, tenant_source
from feedback_ingest.api.schemas import RecordQuery
from feedback_ingest.domain.errors import NotFoundError
from feedback_ingest.domain.models import FeedbackRecord

router = APIRouter(prefix="/v1/records")


@router.get("", response_model_exclude={"__all__": {"tenant_id"}})
def list_records(
    query: Annotated[RecordQuery, Query()], tenant: CurrentTenant, ctx: Ctx
) -> list[FeedbackRecord]:
    if query.source_id is not None:
        tenant_source(query.source_id, tenant, ctx)
    return ctx.adapters.feedback.list_for_tenant(tenant.id, **query.model_dump())


@router.get("/{record_id}", response_model_exclude={"tenant_id"})
def get_record(
    record_id: str, tenant: CurrentTenant, ctx: Ctx, include_deleted: bool = False
) -> FeedbackRecord:
    record = ctx.adapters.feedback.get(record_id, tenant.id)
    if record is None or (record.deleted_at is not None and not include_deleted):
        msg = f"record {record_id} not found"
        raise NotFoundError(msg)
    return record
