"""Organisations API (KAN-59): the caller's organisations and the stores inside them.

Every route needs the internal service key and a verified session, and is rate limited
by subject. The caller's organisations come only from the ``memberships`` table; no
organisation id, owner or role is ever read from a request body (bodies reject unknown
fields). Responses carry ``Cache-Control: no-store``.

``GET /v1/organizations`` is the lookup the frontend uses server-side to find the
caller's organisation ids (for example before calling the billing routes).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.auth import require_internal_key
from app.api.deps import SessionDep, get_session_provider
from app.api.me import CurrentUserIdDep
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.v1.auth import current_subject
from app.core.config import settings
from app.core.database import SessionProvider
from app.core.errors import ErrorResponse
from app.core.rate_limit import API_POLICY
from app.core.slugs import SLUG_MAX_LENGTH, SLUG_MIN_LENGTH, InvalidSlug, ReservedSlug
from app.models.platform.membership import MembershipRole
from app.models.platform.store import StoreStatus
from app.repositories.organizations import OrganizationsRepository, StoreRecord
from app.services.organizations import (
    DEFAULT_PAGE_SIZE,
    MAX_NAME_LENGTH,
    MAX_PAGE_SIZE,
    InvalidName,
    OrganizationLimitReached,
    OrganizationNotFound,
    OrganizationsService,
    OrganizationView,
    OrgForbidden,
    Page,
    SlugTaken,
    StoreLimitReached,
    StoreNotActive,
    StoreNotFound,
)
from app.services.store_provisioning_job import (
    StepEnqueuer,
    get_step_enqueuer,
    start_provisioning,
)

router = APIRouter(
    prefix="/v1/organizations",
    tags=["organizations"],
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
    },
)

OrganizationId = Annotated[
    str, Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]
LimitParam = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
OffsetParam = Annotated[int, Query(ge=0, le=100_000)]
MAX_INPUT_LENGTH = 256
SLUG_RULES = (
    f"Slug must be {SLUG_MIN_LENGTH} to {SLUG_MAX_LENGTH} lowercase letters, digits "
    "or single hyphens, and not start or end with a hyphen"
)
NAME_RULES = (
    f"Name must be 1 to {MAX_NAME_LENGTH} characters, without control characters"
)


class StoreData(BaseModel):
    id: str
    organization_id: str
    name: str
    slug: str
    status: StoreStatus
    created_at: datetime
    updated_at: datetime


class OrganizationData(BaseModel):
    id: str
    name: str
    slug: str
    role: MembershipRole
    created_at: datetime
    updated_at: datetime
    stores: list[StoreData]
    stores_truncated: bool


class OrganizationResponse(BaseModel):
    success: Literal[True] = True
    data: OrganizationData


class OrganizationListResponse(BaseModel):
    success: Literal[True] = True
    data: list[OrganizationData]
    total: int
    limit: int
    offset: int


class StoreResponse(BaseModel):
    success: Literal[True] = True
    data: StoreData


class StoreListResponse(BaseModel):
    success: Literal[True] = True
    data: list[StoreData]
    total: int
    limit: int
    offset: int


class CreateRequest(BaseModel):
    """Body for creating an organisation or a store (name and slug only)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_INPUT_LENGTH)
    slug: str = Field(min_length=1, max_length=MAX_INPUT_LENGTH)


class UpdateRequest(BaseModel):
    """Partial update of a name and/or slug; at least one is required."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=MAX_INPUT_LENGTH)
    slug: str | None = Field(default=None, min_length=1, max_length=MAX_INPUT_LENGTH)

    @model_validator(mode="after")
    def require_a_change(self) -> Self:
        if self.name is None and self.slug is None:
            raise ValueError("no changes supplied")
        return self


@dataclass(frozen=True)
class JobProvisioningStarter:
    provider: SessionProvider
    enqueuer: StepEnqueuer

    async def start(self, store_id: str) -> bool:
        return await start_provisioning(self.provider, self.enqueuer, store_id)


def get_organizations_service(
    session: SessionDep,
    provider: Annotated[SessionProvider, Depends(get_session_provider)],
) -> OrganizationsService:
    return OrganizationsService(
        OrganizationsRepository(session),
        session,
        JobProvisioningStarter(provider, get_step_enqueuer(settings)),
    )


ServiceDep = Annotated[OrganizationsService, Depends(get_organizations_service)]

HANDLED = (
    OrganizationNotFound,
    StoreNotFound,
    OrgForbidden,
    StoreNotActive,
    SlugTaken,
    StoreLimitReached,
    OrganizationLimitReached,
    InvalidName,
    InvalidSlug,
    ReservedSlug,
)


def http_error(exc: Exception) -> HTTPException:
    """Map a service error to a response with a fixed, generic message."""
    if isinstance(exc, OrganizationNotFound):
        return HTTPException(404, "Organization not found")
    if isinstance(exc, StoreNotFound):
        return HTTPException(404, "Store not found")
    if isinstance(exc, OrgForbidden):
        return HTTPException(403, "Forbidden")
    if isinstance(exc, StoreNotActive):
        return HTTPException(403, "Store is not active")
    if isinstance(exc, SlugTaken):
        return HTTPException(409, "Slug is already taken")
    if isinstance(exc, StoreLimitReached):
        return HTTPException(409, str(exc))
    if isinstance(exc, OrganizationLimitReached):
        return HTTPException(409, "Organization limit reached")
    if isinstance(exc, ReservedSlug):
        return HTTPException(422, "Slug is reserved")
    if isinstance(exc, InvalidSlug):
        return HTTPException(422, SLUG_RULES)
    if isinstance(exc, InvalidName):
        return HTTPException(422, NAME_RULES)
    raise exc


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def request_id_of(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def store_data(store: StoreRecord) -> StoreData:
    return StoreData(
        id=store.id,
        organization_id=store.organization_id,
        name=store.name,
        slug=store.slug,
        status=store.status,
        created_at=store.created_at,
        updated_at=store.updated_at,
    )


def organization_data(view: OrganizationView) -> OrganizationData:
    org = view.organization
    return OrganizationData(
        id=org.id,
        name=org.name,
        slug=org.slug,
        role=view.role,
        created_at=org.created_at,
        updated_at=org.updated_at,
        stores=[store_data(store) for store in view.stores],
        stores_truncated=view.stores_truncated,
    )


@router.get("", response_model=OrganizationListResponse)
async def list_organizations(
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
    offset: OffsetParam = 0,
) -> OrganizationListResponse:
    """The caller's own organisations (memberships only), with their role and stores."""
    no_store(response)
    page = await service.list_organizations(user_id, limit, offset)
    return OrganizationListResponse(
        data=[organization_data(view) for view in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("", response_model=OrganizationResponse, status_code=201)
async def create_organization(
    body: CreateRequest,
    request: Request,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
) -> OrganizationResponse:
    """Create an organisation; the caller becomes its OWNER."""
    no_store(response)
    try:
        view = await service.create_organization(
            user_id, name=body.name, slug=body.slug, request_id=request_id_of(request)
        )
    except HANDLED as exc:
        raise http_error(exc) from None
    return OrganizationResponse(data=organization_data(view))


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def read_organization(
    organization_id: OrganizationId,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
) -> OrganizationResponse:
    no_store(response)
    try:
        view = await service.get_organization(organization_id, user_id)
    except HANDLED as exc:
        raise http_error(exc) from None
    return OrganizationResponse(data=organization_data(view))


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: OrganizationId,
    body: UpdateRequest,
    request: Request,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
) -> OrganizationResponse:
    """Rename (OWNER or ADMIN) or change the slug (OWNER only)."""
    no_store(response)
    try:
        view = await service.update_organization(
            organization_id,
            user_id,
            name=body.name,
            slug=body.slug,
            request_id=request_id_of(request),
        )
    except HANDLED as exc:
        raise http_error(exc) from None
    return OrganizationResponse(data=organization_data(view))


@router.get("/{organization_id}/stores", response_model=StoreListResponse)
async def list_organization_stores(
    organization_id: OrganizationId,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
    offset: OffsetParam = 0,
) -> StoreListResponse:
    no_store(response)
    try:
        page: Page[StoreRecord] = await service.list_stores(
            organization_id, user_id, limit, offset
        )
    except HANDLED as exc:
        raise http_error(exc) from None
    return StoreListResponse(
        data=[store_data(store) for store in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/{organization_id}/stores", response_model=StoreResponse, status_code=201)
async def create_store(
    organization_id: OrganizationId,
    body: CreateRequest,
    request: Request,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
) -> StoreResponse:
    """Create a store in PROVISIONING status (OWNER or ADMIN, within the plan limit).

    Provisioning runs in the background (KAN-56). If it cannot be enqueued the store is
    still created and returned with status FAILED.
    """
    no_store(response)
    try:
        store = await service.create_store(
            organization_id,
            user_id,
            name=body.name,
            slug=body.slug,
            request_id=request_id_of(request),
        )
    except HANDLED as exc:
        raise http_error(exc) from None
    return StoreResponse(data=store_data(store))
