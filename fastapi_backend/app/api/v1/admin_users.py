"""Admin users API (KAN-47): list, detail, update, delete, grant/revoke admin, ban/unban.

Every route is ``require_admin(<permission>)``: authentication first (401), then the
admin record and permission (403, one generic body for every denial). Role and
permission changes go through ``AdminUsersService``, which applies the KAN-124
escalation guards and writes the audit row in the same transaction.
"""

import re
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.api.admin import AuditorDep, require_admin
from app.api.auth import require_internal_key
from app.api.deps import SessionDep
from app.api.rate_limit import limit_by_subject
from app.api.v1.auth import current_subject
from app.core.errors import ErrorResponse
from app.core.firebase import (
    FirebaseIdentityProvider,
    IdentityProviderUnavailable,
)
from app.core.permissions import (
    ADMIN_PERMISSIONS,
    ROLE_SUPER_ADMIN,
    WILDCARD,
    AdminContext,
    effective_permissions,
)
from app.core.rate_limit import API_POLICY
from app.repositories.admin_users import AdminUserRecord, AdminUsersRepository
from app.services.admin_users import (
    MAX_PAGE_SIZE,
    AdminActionConflict,
    AdminActionForbidden,
    AdminUsersService,
    OwnershipConflict,
    UserNotFound,
)

router = APIRouter(
    prefix="/v1/admin/users",
    tags=["admin-users"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_subject(API_POLICY, current_subject)),
    ],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)

FORBIDDEN = "Forbidden"
NOT_FOUND = "User not found"
CONFLICT = "Operation not allowed in the current state"

UserId = Annotated[str, Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
ReadAdmin = Annotated[AdminContext, Depends(require_admin("users.read"))]
UpdateAdmin = Annotated[AdminContext, Depends(require_admin("users.update"))]
DeleteAdmin = Annotated[AdminContext, Depends(require_admin("users.delete"))]
GrantAdmin = Annotated[AdminContext, Depends(require_admin("admins.create"))]
RevokeAdmin = Annotated[AdminContext, Depends(require_admin("admins.delete"))]


class AdminUserSummary(BaseModel):
    id: str
    email: str
    email_verified: bool
    display_name: str | None
    avatar_url: str | None
    created_at: datetime
    last_login_at: datetime | None
    is_admin: bool
    admin_role: str | None


class AdminUserDetail(AdminUserSummary):
    bio: str | None
    location: str | None
    website: str | None
    phone_number: str | None
    two_factor_enabled: bool
    admin_permissions: list[str]


class UsersPage(BaseModel):
    users: list[AdminUserSummary]
    total_count: int
    limit: int
    offset: int


class UsersPageResponse(BaseModel):
    success: Literal[True] = True
    data: UsersPage


class UserDetailResponse(BaseModel):
    success: Literal[True] = True
    data: AdminUserDetail


class AdminGrantData(BaseModel):
    user_id: str
    role: str
    permissions: list[str]


class AdminGrantResponse(BaseModel):
    success: Literal[True] = True
    data: AdminGrantData


class OkResponse(BaseModel):
    success: Literal[True] = True


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=100)
    bio: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=100)
    website: str | None = Field(default=None, max_length=2048)
    phone_number: str | None = Field(default=None, max_length=20)
    avatar_url: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def nonempty(self) -> "UpdateUserRequest":
        if not self.model_fields_set:
            raise ValueError("Supply at least one field")
        return self

    @field_validator("website")
    @classmethod
    def http_url(cls, value: str | None) -> str | None:
        if value and not value.startswith(("https://", "http://")):
            raise ValueError("Supply an http(s) URL")
        return value or None

    @field_validator("avatar_url")
    @classmethod
    def https_url(cls, value: str | None) -> str | None:
        if value and not value.startswith("https://"):
            raise ValueError("Supply an HTTPS URL")
        return value or None

    @field_validator("phone_number")
    @classmethod
    def phone(cls, value: str | None) -> str | None:
        if value and not re.fullmatch(r"[0-9+()\-. ]{3,20}", value):
            raise ValueError("Invalid phone number")
        return value or None


class GrantAdminRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["admin", "super_admin"]
    permissions: list[Annotated[str, StringConstraints(max_length=64)]] = Field(
        min_length=1, max_length=len(ADMIN_PERMISSIONS) + 1
    )

    @model_validator(mode="after")
    def known_permissions(self) -> "GrantAdminRequest":
        wanted = set(self.permissions)
        if not wanted <= ADMIN_PERMISSIONS | {WILDCARD}:
            raise ValueError("Unknown permission")
        if (WILDCARD in wanted) != (self.role == ROLE_SUPER_ADMIN):
            raise ValueError("The wildcard and the super_admin role go together")
        if WILDCARD in wanted and wanted != {WILDCARD}:
            raise ValueError("Grant the wildcard on its own")
        return self


class BanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=200)


def get_admin_users_service(
    session: SessionDep, auditor: AuditorDep
) -> AdminUsersService:
    return AdminUsersService(
        AdminUsersRepository(session), session, FirebaseIdentityProvider(), auditor
    )


ServiceDep = Annotated[AdminUsersService, Depends(get_admin_users_service)]


def _summary(user: AdminUserRecord) -> AdminUserSummary:
    return AdminUserSummary(
        id=user.id,
        email=user.email,
        email_verified=user.email_verified,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        is_admin=user.admin_role is not None,
        admin_role=user.admin_role,
    )


def _detail(user: AdminUserRecord) -> AdminUserDetail:
    held = (
        effective_permissions(user.admin_role, user.admin_permissions)
        if user.admin_role
        else frozenset()
    )
    return AdminUserDetail(
        **_summary(user).model_dump(),
        bio=user.bio,
        location=user.location,
        website=user.website,
        phone_number=user.phone_number,
        two_factor_enabled=user.two_factor_enabled,
        admin_permissions=sorted(held),
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


HANDLED = (
    UserNotFound,
    AdminActionForbidden,
    AdminActionConflict,
    OwnershipConflict,
    IdentityProviderUnavailable,
)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, UserNotFound):
        return HTTPException(404, NOT_FOUND)
    if isinstance(exc, AdminActionForbidden):
        return HTTPException(403, FORBIDDEN)
    if isinstance(exc, OwnershipConflict):
        return HTTPException(
            409, "Transfer organization ownership before deleting this user"
        )
    if isinstance(exc, AdminActionConflict):
        return HTTPException(409, CONFLICT)
    return HTTPException(503, "Service temporarily unavailable", {"Retry-After": "5"})


@router.get("", response_model=UsersPageResponse)
async def list_users(
    response: Response,
    _admin: ReadAdmin,
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
) -> UsersPageResponse:
    _no_store(response)
    page = await service.list_users(search, limit, offset)
    return UsersPageResponse(
        data=UsersPage(
            users=[_summary(user) for user in page.users],
            total_count=page.total_count,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/{user_id}", response_model=UserDetailResponse)
async def read_user(
    user_id: UserId, response: Response, _admin: ReadAdmin, service: ServiceDep
) -> UserDetailResponse:
    _no_store(response)
    try:
        return UserDetailResponse(data=_detail(await service.get_user(user_id)))
    except HANDLED as exc:
        raise _http_error(exc) from None


@router.patch("/{user_id}", response_model=UserDetailResponse)
async def update_user(
    user_id: UserId,
    body: UpdateUserRequest,
    response: Response,
    admin: UpdateAdmin,
    service: ServiceDep,
) -> UserDetailResponse:
    _no_store(response)
    try:
        user = await service.update_user(
            admin, user_id, body.model_dump(exclude_unset=True)
        )
    except HANDLED as exc:
        raise _http_error(exc) from None
    return UserDetailResponse(data=_detail(user))


@router.delete("/{user_id}", response_model=OkResponse)
async def delete_user(
    user_id: UserId, response: Response, admin: DeleteAdmin, service: ServiceDep
) -> OkResponse:
    _no_store(response)
    try:
        await service.delete_user(admin, user_id)
    except HANDLED as exc:
        raise _http_error(exc) from None
    return OkResponse()


@router.put("/{user_id}/admin", response_model=AdminGrantResponse)
async def grant_admin(
    user_id: UserId,
    body: GrantAdminRequest,
    response: Response,
    admin: GrantAdmin,
    service: ServiceDep,
) -> AdminGrantResponse:
    _no_store(response)
    try:
        granted = await service.grant_admin(admin, user_id, body.role, body.permissions)
    except HANDLED as exc:
        raise _http_error(exc) from None
    return AdminGrantResponse(data=AdminGrantData(user_id=user_id, **granted))


@router.delete("/{user_id}/admin", response_model=OkResponse)
async def revoke_admin(
    user_id: UserId, response: Response, admin: RevokeAdmin, service: ServiceDep
) -> OkResponse:
    _no_store(response)
    try:
        await service.revoke_admin(admin, user_id)
    except HANDLED as exc:
        raise _http_error(exc) from None
    return OkResponse()


@router.post("/{user_id}/ban", response_model=OkResponse)
async def ban_user(
    user_id: UserId,
    response: Response,
    admin: UpdateAdmin,
    service: ServiceDep,
    body: BanRequest | None = None,
) -> OkResponse:
    _no_store(response)
    try:
        await service.set_banned(admin, user_id, True, body.reason if body else None)
    except HANDLED as exc:
        raise _http_error(exc) from None
    return OkResponse()


@router.post("/{user_id}/unban", response_model=OkResponse)
async def unban_user(
    user_id: UserId, response: Response, admin: UpdateAdmin, service: ServiceDep
) -> OkResponse:
    _no_store(response)
    try:
        await service.set_banned(admin, user_id, False)
    except HANDLED as exc:
        raise _http_error(exc) from None
    return OkResponse()
