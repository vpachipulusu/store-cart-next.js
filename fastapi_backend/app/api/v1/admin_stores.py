"""Admin organisations and stores API (KAN-201): list, suspend, unsuspend, re-run migrations.

Every route is ``require_admin(<permission>)``: authentication first (401), then the
admin record and permission (403, one generic body). Reads need ``stores.read``,
suspend and unsuspend ``stores.suspend``, migrate ``stores.migrate`` and re-running
provisioning of a FAILED store ``stores.reprovision``. Responses never
include the store database reference or connection string. Every change is audited by
``AdminStoresService``; a migration failure is a generic 502 with no driver text.
Success responses carry ``Cache-Control: no-store``; error responses do not.
"""

from collections.abc import Awaitable
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel, Field

from app.api.admin import AuditorDep, require_admin
from app.api.auth import require_internal_key
from app.api.deps import SessionDep, get_session_provider
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.v1.auth import current_subject
from app.core.config import settings
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
    MAX_REPROVISION_ATTEMPTS,
    RETRY_LIMIT_MESSAGE,
    AdminStoreNotFound,
    AdminStoresService,
    CommitFailed,
    MigrationFailed,
    MigrationTimeout,
    ProvisioningNotStarted,
    ReprovisionResult,
    RetryLimitReached,
    StatusResult,
    StoreConflict,
)
from app.services.store_migrations import migrate_store
from app.services.store_provisioning_job import get_step_enqueuer, start_provisioning

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

IDENTIFIER_PATTERN = r"^[A-Za-z0-9_-]+$"
IDENTIFIER_MAX_LENGTH = 128
DEFAULT_PAGE_SIZE = 20
MAX_OFFSET = 1_000_000
SEARCH_PATTERN = r"^[^\x00]*$"  # Postgres text cannot hold NUL
SEARCH_MAX_LENGTH = 100
COMMIT_RETRY_AFTER = 5  # seconds
TIMEOUT_RETRY_AFTER = 30  # seconds

Identifier = Annotated[
    str,
    Path(min_length=1, max_length=IDENTIFIER_MAX_LENGTH, pattern=IDENTIFIER_PATTERN),
]
ReadAdmin = Annotated[AdminContext, Depends(require_admin("stores.read"))]
SuspendAdmin = Annotated[AdminContext, Depends(require_admin("stores.suspend"))]
MigrateAdmin = Annotated[AdminContext, Depends(require_admin("stores.migrate"))]
ReprovisionAdmin = Annotated[AdminContext, Depends(require_admin("stores.reprovision"))]

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No such store."}
}
_STATUS_CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorResponse,
        "description": "The store's status does not allow this operation.",
    }
}
_MIGRATE_CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorResponse,
        "description": "The store is PROVISIONING or ARCHIVED, or this process is "
        "already migrating it.",
    }
}
_REPROVISION_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_NOT_FOUND,
    409: {
        "model": ErrorResponse,
        "description": "The store is not FAILED, or it was already re-run the "
        "maximum number of times (`MAX_REPROVISION_ATTEMPTS`).",
    },
    502: {
        "model": ErrorResponse,
        "description": "The job could not be enqueued; the store is FAILED again and "
        "the attempt does not count against the cap.",
    },
    503: {
        "model": ErrorResponse,
        "description": "The change or its audit row could not be recorded and was "
        f"rolled back. Retry after `Retry-After` seconds ({COMMIT_RETRY_AFTER}). Also "
        "returned when the rate limiter is unavailable.",
    },
}
_STATUS_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_NOT_FOUND,
    **_STATUS_CONFLICT,
    503: {
        "model": ErrorResponse,
        "description": "The change or its audit row could not be recorded and was "
        f"rolled back. Retry after `Retry-After` seconds ({COMMIT_RETRY_AFTER}). Also "
        "returned when the rate limiter is unavailable.",
    },
}
_MIGRATE_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_NOT_FOUND,
    **_MIGRATE_CONFLICT,
    502: {
        "model": ErrorResponse,
        "description": "The store database could not be migrated. Generic body; the "
        "audit row carries the reason. Re-running is safe.",
    },
    503: {
        "model": ErrorResponse,
        "description": "The migration did not finish in time (`Retry-After` "
        f"{TIMEOUT_RETRY_AFTER} seconds; it may have partly run, outcome unknown) or "
        f"its result could not be recorded (`Retry-After` {COMMIT_RETRY_AFTER} "
        "seconds). Re-run the migration; it is idempotent. Also returned when the "
        "rate limiter is unavailable.",
    },
}


class OrganizationSummary(BaseModel):
    id: str
    name: str
    slug: str
    store_count: int = Field(description="Stores of the organisation, any status.")
    created_at: datetime


class OrganizationsPage(BaseModel):
    organizations: list[OrganizationSummary]
    total_count: int = Field(description="Organisations matching `search`, all pages.")
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
    schema_version: int = Field(description="Store migrations applied.")
    created_at: datetime
    updated_at: datetime


class AdminStoresPage(BaseModel):
    stores: list[StoreSummary]
    total_count: int = Field(description="Stores matching the filters, all pages.")
    limit: int
    offset: int


class AdminStoresPageResponse(BaseModel):
    success: Literal[True] = True
    data: AdminStoresPage


class StoreStatusData(BaseModel):
    store_id: str
    status: StoreStatus
    changed: bool = Field(description="False when the store was already in that state.")


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


class StoreReprovisionData(BaseModel):
    store_id: str
    status: StoreStatus
    attempt: int = Field(description="Which re-run this was, starting at 1.")
    max_attempts: int


class StoreReprovisionResponse(BaseModel):
    success: Literal[True] = True
    data: StoreReprovisionData


def get_admin_stores_service(
    session: SessionDep,
    auditor: AuditorDep,
    provider: Annotated[SessionProvider, Depends(get_session_provider)],
) -> AdminStoresService:
    async def migrate(store_id: str) -> int:
        return await migrate_store(store_id, provider)

    async def start(store_id: str, attempt: int) -> bool:
        # Built per call: only re-runs need the enqueuer.
        enqueuer = get_step_enqueuer(settings)
        return await start_provisioning(provider, enqueuer, store_id, attempt=attempt)

    return AdminStoresService(
        AdminStoresRepository(session),
        session,
        auditor,
        migrate,
        start_provisioning=start,
    )


ServiceDep = Annotated[AdminStoresService, Depends(get_admin_stores_service)]

# Every domain error the service raises, with its (status, detail, headers).
_ERRORS: dict[type[Exception], tuple[int, str, dict[str, str] | None]] = {
    AdminStoreNotFound: (404, "Store not found", None),
    StoreConflict: (409, "Operation not allowed in the current state", None),
    RetryLimitReached: (409, RETRY_LIMIT_MESSAGE, None),
    ProvisioningNotStarted: (502, "Provisioning could not be started", None),
    MigrationFailed: (502, "Store migration failed", None),
    CommitFailed: (
        503,
        "The result could not be recorded; retry",
        {"Retry-After": str(COMMIT_RETRY_AFTER)},
    ),
    MigrationTimeout: (
        503,
        "Store migration did not finish in time; re-run it",
        {"Retry-After": str(TIMEOUT_RETRY_AFTER)},
    ),
}
HANDLED = tuple(_ERRORS)


def _http_error(exc: Exception) -> HTTPException:
    mapped = next((_ERRORS[t] for t in type(exc).__mro__ if t in _ERRORS), None)
    if mapped is None:
        raise TypeError(f"unmapped admin stores error: {type(exc).__name__}")
    status_code, detail, headers = mapped
    return HTTPException(status_code, detail, headers=headers)


# Shared with the merchant retry route (KAN-242), which maps the same domain errors.
http_error = _http_error


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


async def _change_status(
    change: Awaitable[StatusResult], store_id: str, response: Response
) -> StoreStatusResponse:
    _no_store(response)
    try:
        result = await change
    except HANDLED as exc:
        raise _http_error(exc) from None
    return StoreStatusResponse(
        data=StoreStatusData(
            store_id=store_id, status=result.status, changed=result.changed
        )
    )


@router.get(
    "/organizations",
    response_model=OrganizationsPageResponse,
    summary="List organisations with their store counts",
)
async def admin_list_organizations(
    response: Response,
    _admin: ReadAdmin,
    service: ServiceDep,
    search: Annotated[
        str | None,
        Query(
            max_length=SEARCH_MAX_LENGTH,
            pattern=SEARCH_PATTERN,
            description="Case-insensitive match on name or slug; % and _ are literal.",
        ),
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Page size.")
    ] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET, description="Rows to skip.")] = 0,
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


@router.get(
    "/stores",
    response_model=AdminStoresPageResponse,
    summary="List stores with status and schema version",
)
async def admin_list_stores(
    response: Response,
    _admin: ReadAdmin,
    service: ServiceDep,
    status: Annotated[
        StoreStatus | None, Query(description="Only stores in this status.")
    ] = None,
    organization_id: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=IDENTIFIER_MAX_LENGTH,
            pattern=IDENTIFIER_PATTERN,
            description="Only stores of this organisation.",
        ),
    ] = None,
    search: Annotated[
        str | None,
        Query(
            max_length=SEARCH_MAX_LENGTH,
            pattern=SEARCH_PATTERN,
            description="Case-insensitive match on name or slug; % and _ are literal.",
        ),
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Page size.")
    ] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET, description="Rows to skip.")] = 0,
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


@router.post(
    "/stores/{store_id}/suspend",
    summary="Suspend a store",
    response_model=StoreStatusResponse,
    responses=_STATUS_RESPONSES,
)
async def admin_suspend_store(
    store_id: Identifier, response: Response, admin: SuspendAdmin, service: ServiceDep
) -> StoreStatusResponse:
    return await _change_status(service.suspend(admin, store_id), store_id, response)


@router.post(
    "/stores/{store_id}/unsuspend",
    summary="Unsuspend a store",
    response_model=StoreStatusResponse,
    responses=_STATUS_RESPONSES,
)
async def admin_unsuspend_store(
    store_id: Identifier, response: Response, admin: SuspendAdmin, service: ServiceDep
) -> StoreStatusResponse:
    return await _change_status(service.unsuspend(admin, store_id), store_id, response)


@router.post(
    "/stores/{store_id}/migrate",
    summary="Re-run a store's database migrations",
    response_model=StoreMigrationResponse,
    responses=_MIGRATE_RESPONSES,
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


@router.post(
    "/stores/{store_id}/reprovision",
    summary="Re-run provisioning of a FAILED store",
    response_model=StoreReprovisionResponse,
    responses=_REPROVISION_RESPONSES,
)
async def admin_reprovision_store(
    store_id: Identifier,
    response: Response,
    admin: ReprovisionAdmin,
    service: ServiceDep,
) -> StoreReprovisionResponse:
    _no_store(response)
    try:
        result: ReprovisionResult = await service.reprovision(admin, store_id)
    except HANDLED as exc:
        raise _http_error(exc) from None
    return StoreReprovisionResponse(
        data=StoreReprovisionData(
            store_id=store_id,
            status=result.status,
            attempt=result.attempt,
            max_attempts=MAX_REPROVISION_ATTEMPTS,
        )
    )
