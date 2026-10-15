"""Platform admin audit log API (KAN-49): list and filter, newest first.

Platform admins only (``audit.read``): authentication first (401), then the admin
record and permission (403, one generic body). A merchant, including the owner of
the organisation concerned, can never read these rows.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

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
MAX_OFFSET = 10_000
OrganizationIdFilter = Annotated[
    str | None,
    Query(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Only rows for this organisation id (exact match).",
    ),
]
StoreIdFilter = Annotated[
    str | None,
    Query(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Only rows for this store id (exact match).",
    ),
]
UserIdFilter = Annotated[
    str | None,
    Query(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Only rows written by this acting user id (exact match).",
    ),
]
ActionName = Annotated[
    str | None,
    Query(
        min_length=3,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$",
        description="Only rows with this action, for example `store.update` (exact match).",
    ),
]
CreatedFrom = Annotated[
    datetime | None,
    Query(description="Only rows created at or after this instant (ISO 8601)."),
]
CreatedTo = Annotated[
    datetime | None,
    Query(description="Only rows created at or before this instant (ISO 8601)."),
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
    metadata: Any = Field(
        description=(
            "Sanitised JSON object, or null. Keys: `actor_role` and `request_id` (admin "
            "routes), `before`, `after` and `details` (changed fields; secret-looking "
            "keys and values are `[REDACTED]`). Billing rows carry `details` only."
        ),
    )
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
    return AuditLogEntry.model_validate(entry, from_attributes=True)


@router.get(
    "",
    response_model=AuditLogPageResponse,
    summary="List audit log entries",
    description=(
        "Newest first. Requires the `audit.read` admin permission. Filters combine "
        "with AND. `total_count` is the number of rows matching the filters. "
        f"`offset` is capped at {MAX_OFFSET:,}: narrow the filters or the date range "
        "to reach older rows."
    ),
)
async def list_audit_logs(
    response: Response,
    _admin: ReadAdmin,
    service: ServiceDep,
    organization_id: OrganizationIdFilter = None,
    store_id: StoreIdFilter = None,
    user_id: UserIdFilter = None,
    action: ActionName = None,
    created_from: CreatedFrom = None,
    created_to: CreatedTo = None,
    limit: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Page size (1 to 100).")
    ] = 50,
    offset: Annotated[
        int, Query(ge=0, le=MAX_OFFSET, description="Rows to skip (0 to 10,000).")
    ] = 0,
) -> AuditLogPageResponse:
    response.headers["Cache-Control"] = "no-store"
    if created_from and created_to and created_from > created_to:
        raise HTTPException(422, "created_from must not be after created_to")
    page = await service.list_entries(
        AuditFilters(
            organization_id, store_id, user_id, action, created_from, created_to
        ),
        limit,
        offset,
    )
    return AuditLogPageResponse(
        data=AuditLogPage(
            entries=[_entry(entry) for entry in page.entries],
            total_count=page.total_count,
            limit=limit,
            offset=offset,
        )
    )
