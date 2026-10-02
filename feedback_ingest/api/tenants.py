import hmac
import secrets
from http import HTTPStatus
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException

from feedback_ingest.api.deps import Ctx
from feedback_ingest.api.schemas import TenantCreate, TenantCreated
from feedback_ingest.domain.errors import UnauthorizedError
from feedback_ingest.domain.models import Tenant
from feedback_ingest.utils.hashing import sha256_text

router = APIRouter(prefix="/admin")


# ponytail: shared bootstrap token; real deployments put this behind an ops identity
@router.post("/tenants", status_code=HTTPStatus.CREATED)
def create_tenant(
    body: TenantCreate,
    ctx: Ctx,
    x_bootstrap_token: Annotated[str, Header(alias="X-Bootstrap-Token")] = "",
) -> TenantCreated:
    expected = ctx.settings.bootstrap_token
    if not expected or not hmac.compare_digest(x_bootstrap_token.encode(), expected.encode()):
        msg = "missing or wrong X-Bootstrap-Token"
        raise UnauthorizedError(msg)
    api_key = secrets.token_urlsafe(32)
    tenant = Tenant(id=uuid4().hex, name=body.name, api_key_hash=sha256_text(api_key))
    try:
        ctx.adapters.tenants.add(tenant)
    except ValueError as exc:
        raise HTTPException(HTTPStatus.CONFLICT, detail=f"tenant {body.name!r} exists") from exc
    return TenantCreated(id=tenant.id, name=tenant.name, api_key=api_key)
