"""Admin organisations and stores API (KAN-201): list, suspend, unsuspend, re-run migrations.

Every route is ``require_admin(<permission>)``: authentication first (401), then the
admin record and permission (403, one generic body). Reads need ``stores.read``,
suspend and unsuspend ``stores.suspend`` and migrate ``stores.migrate``. Responses never
include the store database reference or connection string. Every change is audited by
``AdminStoresService``; a migration failure is a generic 502 with no driver text.
"""

from datetime import datetime
from typing import Annotated, Literal

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
    AdminStoresService,
    MigrationFailed,
    MigrationTimeout,
    StoreConflict,
    StoreNotFound,
)
from app.services.store_migrations import migrate_store

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
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)

Identifier = Annotated[
    str, Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]
ReadAdmin = Annotated[AdminContext, Depends(require_admin("stores.read"))]
SuspendAdmin = Annotated[AdminContext, Depends(require_admin("stores.suspend"))]
MigrateAdmin = Annotated[AdminContext, Depends(require_admin("stores.migrate"))]
StatusName = Literal["PROVISIONING", "ACTIVE", "SUSPENDED", "ARCHIVED"]


class OrganizationSummary(BaseModel):
    id: str
    name: str
    slug: str
    store_count: int
    created_at: datetime


class OrganizationsPage(BaseModel):
    organizations: list[OrganizationSummary]
    total_count: int
    limit: int
    offset: int


class OrganizationsPageResponse(BaseModel):
    success: Literal[True] = True
    data: OrganizationsPage


class StoreSummary(BaseModel):
    id: str
    organization_id: str
    organization_name: str
    name: str
    slug: str
    status: StoreStatus
    schema_version: int
    created_at: datetime
    updated_at: datetime


class StoresPage(BaseModel):
    stores: list[StoreSummary]
    total_count: int
    limit: int
    offset: int


class StoresPageResponse(BaseModel):
    success: Literal[True] = True
    data: StoresPage


class StatusData(BaseModel):
    store_id: str
    status: StoreStatus
    changed: bool


class StatusResponse(BaseModel):
    success: Literal[True] = True
    data: StatusData


class MigrateData(BaseModel):
    store_id: str
    previous_schema_version: int
    schema_version: int


class MigrateResponse(BaseModel):
    success: Literal[True] = True
    data: MigrateData


def get_admin_stores_service(
    session: SessionDep,
    auditor: AuditorDep,
    provider: Annotated[SessionProvider, Depends(get_session_provider)],
) -> AdminStoresService:
    async def migrate(store_id: str) -> int:
        return await migrate_store(store_id, provider)

    return AdminStoresService(AdminStoresRepository(session), session, auditor, migrate)


ServiceDep = Annotated[AdminStoresService, Depends(get_admin_stores_service)]

HANDLED = (StoreNotFound, StoreConflict, MigrationFailed, MigrationTimeout)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, StoreNotFound):
        return HTTPException(404, "Store not found")
    if isinstance(exc, StoreConflict):
        return HTTPException(409, "Operation not allowed in the current state")
    if isinstance(exc, MigrationFailed):
        return HTTPException(502, "Store migration failed")
    return HTTPException(
        503, "Store migration did not finish in time; retry", {"Retry-After": "30"}
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _organization(record: OrganizationRecord) -> OrganizationSummary:
    return OrganizationSummary(
        id=record.id,
        name=record.name,
        slug=record.slug,
        store_count=record.store_count,
        created_at=record.created_at,
    )


def _store(record: StoreRecord) -> StoreSummary:
    return StoreSummary(
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


@router.get("/organizations", response_model=OrganizationsPageResponse)
async def admin_list_organizations(
    response: Response,
    _admin: ReadAdmin,
    service: ServiceDep,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> OrganizationsPageResponse:
    _no_store(response)
    page = await service.list_organizations(search, limit, offset)
    return OrganizationsPageResponse(
        data=OrganizationsPage(
            organizations=[_organization(item) for item in page.items],
            total_count=page.total_count,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/stores", response_model=StoresPageResponse)
async def admin_list_stores(
    response: Response,
    _admin: ReadAdmin,
    service: ServiceDep,
    status: StatusName | None = None,
    organization_id: Annotated[
        str | None, Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    ] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> StoresPageResponse:
    _no_store(response)
    filters = StoreFilters(
        StoreStatus(status) if status else None, organization_id, search
    )
    page = await service.list_stores(filters, limit, offset)
    return StoresPageResponse(
        data=StoresPage(
            stores=[_store(item) for item in page.items],
            total_count=page.total_count,
            limit=limit,
            offset=offset,
        )
    )


@router.post("/stores/{store_id}/suspend", response_model=StatusResponse)
async def admin_suspend_store(
    store_id: Identifier, response: Response, admin: SuspendAdmin, service: ServiceDep
) -> StatusResponse:
    _no_store(response)
    try:
        result = await service.suspend(admin, store_id)
    except HANDLED as exc:
        raise _http_error(exc) from None
    return StatusResponse(
        data=StatusData(store_id=store_id, status=result.status, changed=result.changed)
    )


@router.post("/stores/{store_id}/unsuspend", response_model=StatusResponse)
async def admin_unsuspend_store(
    store_id: Identifier, response: Response, admin: SuspendAdmin, service: ServiceDep
) -> StatusResponse:
    _no_store(response)
    try:
        result = await service.unsuspend(admin, store_id)
    except HANDLED as exc:
        raise _http_error(exc) from None
    return StatusResponse(
        data=StatusData(store_id=store_id, status=result.status, changed=result.changed)
    )


@router.post("/stores/{store_id}/migrate", response_model=MigrateResponse)
async def admin_migrate_store(
    store_id: Identifier, response: Response, admin: MigrateAdmin, service: ServiceDep
) -> MigrateResponse:
    _no_store(response)
    try:
        result = await service.migrate(admin, store_id)
    except HANDLED as exc:
        raise _http_error(exc) from None
    return MigrateResponse(
        data=MigrateData(
            store_id=store_id,
            previous_schema_version=result.previous_version,
            schema_version=result.schema_version,
        )
    )
