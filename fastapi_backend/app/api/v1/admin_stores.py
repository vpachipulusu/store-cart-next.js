"""Admin organisations and stores API (KAN-201): list, suspend, unsuspend, re-run migrations.

Every route is ``require_admin(<permission>)``: authentication first (401), then the
admin record and permission (403, one generic body). Reads need ``stores.read``,
suspend and unsuspend ``stores.suspend`` and migrate ``stores.migrate``. Responses never
include the store database reference or connection string. Every change is audited by
``AdminStoresService``; a migration failure is a generic 502 with no driver text.
``Cache-Control: no-store`` is set on success responses only.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel

from app.api.admin import AuditorDep, require_admin
from app.api.auth import require_internal_key
from app.api.deps import SessionDep, get_session_provider
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.v1.auth import current_subject
from app.core.database import SessionProvider
from app.core.errors import ErrorResponse
from app.core.permissions import AdminContext
from app.core.rate_limit import API_POLICY
from app.models.platform.store import StoreStatus
from app.repositories.admin_stores import (
    AdminStoresRepository,
    OrganizationRecord,
    StoreFilters,
    StoreRecord,
)
from app.services.admin_stores import (
    MAX_PAGE_SIZE,
    AdminStoreNotFound,
    AdminStoresService,
    CommitFailed,
    MigrationFailed,
    MigrationTimeout,
    StatusResult,
    StoreConflict,
)
from app.services.store_migrations import migrate_store

DEFAULT_PAGE_SIZE = 20
MAX_OFFSET = 1_000_000
MAX_SEARCH_LENGTH = 100
ID_PATTERN = r"^[A-Za-z0-9_-]+$"
# Postgres text cannot hold NUL.
SEARCH_PATTERN = r"^[^\x00]*$"

router = APIRouter(
    prefix="/v1/admin",
    tags=["admin-stores"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_subject(API_POLICY, current_subject)),
    ],
    responses={
        **RATE_LIMIT_FAIL_CLOSED_RESPONSES,
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)

NOT_FOUND = {"model": ErrorResponse, "description": "No such store"}
CONFLICT = {
    "model": ErrorResponse,
    "description": "The status does not allow this, or a migration is already running",
}
UNAVAILABLE_RETRY = {
    "model": ErrorResponse,
    "description": (
        "The change could not be recorded (Retry-After: 5; retrying is safe), or the "
        "rate limiter is unavailable"
    ),
}
MIGRATE_FAILED = {
    "model": ErrorResponse,
    "description": "The store database could not be migrated; no driver text is returned",
}
MIGRATE_UNAVAILABLE = {
    "model": ErrorResponse,
    "description": (
        "The migration did not finish within 60 seconds (Retry-After: 30; the outcome is "
        "unknown, re-running is safe and repairs the version), or the result could not "
        "be recorded (Retry-After: 5), or the rate limiter is unavailable"
    ),
}

Identifier = Annotated[str, Path(min_length=1, max_length=128, pattern=ID_PATTERN)]
ReadAdmin = Annotated[AdminContext, Depends(require_admin("stores.read"))]
SuspendAdmin = Annotated[AdminContext, Depends(require_admin("stores.suspend"))]
MigrateAdmin = Annotated[AdminContext, Depends(require_admin("stores.migrate"))]
SearchQuery = Annotated[
    str | None, Query(max_length=MAX_SEARCH_LENGTH, pattern=SEARCH_PATTERN)
]
LimitQuery = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
OffsetQuery = Annotated[int, Query(ge=0, le=MAX_OFFSET)]


class AdminOrganizationSummary(BaseModel):
    id: str
    name: str
    slug: str
    store_count: int
    created_at: datetime


class AdminOrganizationsPage(BaseModel):
    organizations: list[AdminOrganizationSummary]
    total_count: int
    limit: int
    offset: int


class AdminOrganizationsPageResponse(BaseModel):
    success: Literal[True] = True
    data: AdminOrganizationsPage


class AdminStoreSummary(BaseModel):
    id: str
    organization_id: str
    organization_name: str
    name: str
    slug: str
    status: StoreStatus
    schema_version: int
    created_at: datetime
    updated_at: datetime


class AdminStoresPage(BaseModel):
    stores: list[AdminStoreSummary]
    total_count: int
    limit: int
    offset: int


class AdminStoresPageResponse(BaseModel):
    success: Literal[True] = True
    data: AdminStoresPage


class StoreStatusData(BaseModel):
    store_id: str
    status: StoreStatus
    changed: bool


class StoreStatusResponse(BaseModel):
    success: Literal[True] = True
    data: StoreStatusData


class StoreMigrationData(BaseModel):
    store_id: str
    previous_schema_version: int
    schema_version: int


class StoreMigrationResponse(BaseModel):
    success: Literal[True] = True
    data: StoreMigrationData


def get_admin_stores_service(
    session: SessionDep,
    auditor: AuditorDep,
    provider: Annotated[SessionProvider, Depends(get_session_provider)],
) -> AdminStoresService:
    async def migrate(store_id: str) -> int:
        return await migrate_store(store_id, provider)

    return AdminStoresService(AdminStoresRepository(session), session, auditor, migrate)


ServiceDep = Annotated[AdminStoresService, Depends(get_admin_stores_service)]

# One entry per service error: (status, detail, headers). An unmapped error is a bug.
ERRORS: dict[type[Exception], tuple[int, str, dict[str, str] | None]] = {
    AdminStoreNotFound: (404, "Store not found", None),
    StoreConflict: (409, "Operation not allowed in the current state", None),
    MigrationFailed: (502, "Store migration failed", None),
    CommitFailed: (
        503,
        "The result could not be recorded; retry",
        {"Retry-After": "5"},
    ),
    MigrationTimeout: (
        503,
        "Store migration did not finish in time; re-run it",
        {"Retry-After": "30"},
    ),
}
HANDLED = tuple(ERRORS)


def _http_error(exc: Exception) -> HTTPException:
    try:
        status, detail, headers = ERRORS[type(exc)]
    except KeyError:
        raise TypeError(f"No HTTP mapping for {type(exc).__name__}") from None
    return HTTPException(status, detail, headers)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _organization(record: OrganizationRecord) -> AdminOrganizationSummary:
    return AdminOrganizationSummary(
        id=record.id,
        name=record.name,
        slug=record.slug,
        store_count=record.store_count,
        created_at=record.created_at,
    )


def _store(record: StoreRecord) -> AdminStoreSummary:
    return AdminStoreSummary(
        id=record.id,
        organization_id=record.organization_id,
        organization_name=record.organization_name,
        name=record.name,
        slug=record.slug,
        status=record.status,
        schema_version=record.schema_version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("/organizations", response_model=AdminOrganizationsPageResponse)
async def admin_list_organizations(
    response: Response,
    _admin: ReadAdmin,
    service: ServiceDep,
    search: SearchQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    offset: OffsetQuery = 0,
) -> AdminOrganizationsPageResponse:
    _no_store(response)
    page = await service.list_organizations(search, limit, offset)
    return AdminOrganizationsPageResponse(
        data=AdminOrganizationsPage(
            organizations=[_organization(item) for item in page.items],
            total_count=page.total_count,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/stores", response_model=AdminStoresPageResponse)
async def admin_list_stores(
    response: Response,
    _admin: ReadAdmin,
    service: ServiceDep,
    status: StoreStatus | None = None,
    organization_id: Annotated[
        str | None, Query(min_length=1, max_length=128, pattern=ID_PATTERN)
    ] = None,
    search: SearchQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    offset: OffsetQuery = 0,
) -> AdminStoresPageResponse:
    _no_store(response)
    filters = StoreFilters(status, organization_id, search)
    page = await service.list_stores(filters, limit, offset)
    return AdminStoresPageResponse(
        data=AdminStoresPage(
            stores=[_store(item) for item in page.items],
            total_count=page.total_count,
            limit=limit,
            offset=offset,
        )
    )


async def _change_status(
    response: Response,
    store_id: str,
    change: Callable[[str], Awaitable[StatusResult]],
) -> StoreStatusResponse:
    _no_store(response)
    try:
        result = await change(store_id)
    except HANDLED as exc:
        raise _http_error(exc) from None
    return StoreStatusResponse(
        data=StoreStatusData(
            store_id=store_id, status=result.status, changed=result.changed
        )
    )


STATUS_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: NOT_FOUND,
    409: CONFLICT,
    503: UNAVAILABLE_RETRY,
}


@router.post(
    "/stores/{store_id}/suspend",
    response_model=StoreStatusResponse,
    responses=STATUS_RESPONSES,
)
async def admin_suspend_store(
    store_id: Identifier, response: Response, admin: SuspendAdmin, service: ServiceDep
) -> StoreStatusResponse:
    return await _change_status(
        response, store_id, lambda sid: service.suspend(admin, sid)
    )


@router.post(
    "/stores/{store_id}/unsuspend",
    response_model=StoreStatusResponse,
    responses=STATUS_RESPONSES,
)
async def admin_unsuspend_store(
    store_id: Identifier, response: Response, admin: SuspendAdmin, service: ServiceDep
) -> StoreStatusResponse:
    return await _change_status(
        response, store_id, lambda sid: service.unsuspend(admin, sid)
    )


@router.post(
    "/stores/{store_id}/migrate",
    response_model=StoreMigrationResponse,
    responses={
        404: NOT_FOUND,
        409: CONFLICT,
        502: MIGRATE_FAILED,
        503: MIGRATE_UNAVAILABLE,
    },
)
async def admin_migrate_store(
    store_id: Identifier, response: Response, admin: MigrateAdmin, service: ServiceDep
) -> StoreMigrationResponse:
    _no_store(response)
    try:
        result = await service.migrate(admin, store_id)
    except HANDLED as exc:
        raise _http_error(exc) from None
    return StoreMigrationResponse(
        data=StoreMigrationData(
            store_id=store_id,
            previous_schema_version=result.previous_version,
            schema_version=result.schema_version,
        )
    )
