"""Platform admin audit log API (KAN-49): list and filter, newest first.

Platform admins only (``audit.read``): authentication first (401), then the admin
record and permission (403, one generic body). A merchant, including the owner of
the organisation concerned, can never read these rows.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from app.api.admin import require_admin
from app.api.auth import require_internal_key
from app.api.deps import SessionDep
from app.api.rate_limit import limit_by_subject
from app.api.v1.auth import current_subject
from app.core.errors import ErrorResponse
from app.core.permissions import AdminContext
from app.core.rate_limit import API_POLICY
from app.repositories.audit import AuditEntry, AuditFilters, AuditReader
from app.services.audit_logs import MAX_PAGE_SIZE, AuditLogsService

router = APIRouter(
    prefix="/v1/admin/audit-logs",
    tags=["admin-audit-logs"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_subject(API_POLICY, current_subject)),
    ],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)

ReadAdmin = Annotated[AdminContext, Depends(require_admin("audit.read"))]
TargetId = Annotated[
    str | None, Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]
ActionName = Annotated[
    str | None,
    Query(
        min_length=3, max_length=100, pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"
    ),
]


class AuditLogEntry(BaseModel):
    id: str
    created_at: datetime
    user_id: str | None
    organization_id: str | None
    store_id: str | None
    action: str
    resource: str
    resource_id: str | None
    metadata: Any
    ip_address: str | None
    user_agent: str | None


class AuditLogPage(BaseModel):
    entries: list[AuditLogEntry]
    total_count: int
    limit: int
    offset: int


class AuditLogPageResponse(BaseModel):
    success: Literal[True] = True
    data: AuditLogPage


def get_audit_logs_service(session: SessionDep) -> AuditLogsService:
    return AuditLogsService(AuditReader(session))


ServiceDep = Annotated[AuditLogsService, Depends(get_audit_logs_service)]


def _entry(entry: AuditEntry) -> AuditLogEntry:
    return AuditLogEntry(**vars(entry))


@router.get("", response_model=AuditLogPageResponse)
async def list_audit_logs(
    response: Response,
    _admin: ReadAdmin,
    service: ServiceDep,
    organization_id: TargetId = None,
    store_id: TargetId = None,
    user_id: TargetId = None,
    action: ActionName = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> AuditLogPageResponse:
    response.headers["Cache-Control"] = "no-store"
    page = await service.list_entries(
        AuditFilters(organization_id, store_id, user_id, action), limit, offset
    )
    return AuditLogPageResponse(
        data=AuditLogPage(
            entries=[_entry(entry) for entry in page.entries],
            total_count=page.total_count,
            limit=limit,
            offset=offset,
        )
    )
