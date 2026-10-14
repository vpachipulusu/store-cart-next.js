from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

from app.api.auth import auth_error, require_internal_key
from app.api.me import (
    CurrentIdentityDep,
    CurrentUserIdDep,
    MeServiceDep,
    PreferencesServiceDep,
)
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.v1.auth import current_subject
from app.core.errors import ErrorResponse
from app.core.firebase import AuthenticationFailed, IdentityProviderUnavailable
from app.core.rate_limit import API_POLICY, AUTH_POLICY
from app.services.me import OwnershipConflict, UserNotFound

router = APIRouter(
    prefix="/v1/me",
    tags=["me"],
    dependencies=[Depends(require_internal_key)],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)


class ProfileData(BaseModel):
    id: str
    email: str
    email_verified: bool
    two_factor_enabled: bool
    display_name: str | None
    bio: str | None
    avatar_url: str | None
    location: str | None
    website: str | None
    phone_number: str | None
    created_at: datetime


class ProfileResponse(BaseModel):
    success: Literal[True] = True
    data: ProfileData


class PartialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def nonempty(self) -> "PartialRequest":
        if not self.model_fields_set:
            raise ValueError("Supply at least one field")
        return self


class ProfileRequest(PartialRequest):
    display_name: str | None = Field(default=None, max_length=100)
    bio: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=100)
    website: str | None = Field(default=None, max_length=2048)
    phone_number: str | None = Field(default=None, max_length=20)

    @field_validator("website")
    @classmethod
    def website_url(cls, value: str | None) -> str | None:
        if not value:
            return None
        parsed = HttpUrl(value)
        if parsed.username or parsed.password:
            raise ValueError("Credentials are not permitted in URLs")
        return value


class AvatarRequest(PartialRequest):
    avatar_url: str | None = Field(default=None, max_length=2048)

    @field_validator("avatar_url")
    @classmethod
    def avatar_url_https(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = HttpUrl(value)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise ValueError("Supply an HTTPS URL without credentials")
        return value


class SettingsData(BaseModel):
    theme: str
    email_notifications: bool
    language: str
    timezone: str


class SettingsResponse(BaseModel):
    success: Literal[True] = True
    data: SettingsData


class SettingsRequest(PartialRequest):
    theme: Literal["light", "dark", "system"] | SkipJsonSchema[None] = None
    email_notifications: Annotated[bool, Field(strict=True)] | SkipJsonSchema[None] = (
        None
    )
    language: str | SkipJsonSchema[None] = Field(
        default=None, min_length=2, max_length=5
    )
    timezone: str | SkipJsonSchema[None] = Field(
        default=None, min_length=1, max_length=100
    )

    @model_validator(mode="after")
    def no_null_fields(self) -> "SettingsRequest":
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Settings cannot be null")
        return self


class HistoryEntry(BaseModel):
    id: str
    ip_address: str | None
    user_agent: str | None
    location: str | None
    login_at: datetime
    successful: bool


class HistoryData(BaseModel):
    login_history: list[HistoryEntry]
    total_count: int


class HistoryResponse(BaseModel):
    success: Literal[True] = True
    data: HistoryData


class DeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id_token: SecretStr = Field(min_length=1, max_length=16384)


class DeletedResponse(BaseModel):
    success: Literal[True] = True


api_limit = [Depends(limit_by_subject(API_POLICY, current_subject))]


@router.get("", response_model=ProfileResponse, dependencies=api_limit)
async def read_profile(
    response: Response, identity: CurrentIdentityDep, service: MeServiceDep
) -> ProfileResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        profile = await service.get_profile(identity.uid)
    except UserNotFound:
        raise HTTPException(404, "User not found") from None
    return ProfileResponse(data=ProfileData(**asdict(profile)))


@router.patch("", response_model=ProfileResponse, dependencies=api_limit)
async def update_profile(
    body: ProfileRequest,
    response: Response,
    identity: CurrentIdentityDep,
    service: MeServiceDep,
) -> ProfileResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        profile = await service.update_profile(
            identity.uid, body.model_dump(exclude_unset=True)
        )
    except UserNotFound:
        raise HTTPException(404, "User not found") from None
    return ProfileResponse(data=ProfileData(**asdict(profile)))


@router.patch("/avatar", response_model=ProfileResponse, dependencies=api_limit)
async def update_avatar(
    body: AvatarRequest,
    response: Response,
    identity: CurrentIdentityDep,
    service: MeServiceDep,
) -> ProfileResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        profile = await service.update_profile(
            identity.uid, body.model_dump(exclude_unset=True)
        )
    except UserNotFound:
        raise HTTPException(404, "User not found") from None
    return ProfileResponse(data=ProfileData(**asdict(profile)))


@router.get("/settings", response_model=SettingsResponse, dependencies=api_limit)
async def read_settings(
    response: Response, user_id: CurrentUserIdDep, service: PreferencesServiceDep
) -> SettingsResponse:
    response.headers["Cache-Control"] = "no-store"
    return SettingsResponse(
        data=SettingsData(**asdict(await service.get_settings(user_id)))
    )


@router.patch("/settings", response_model=SettingsResponse, dependencies=api_limit)
async def update_settings(
    body: SettingsRequest,
    response: Response,
    user_id: CurrentUserIdDep,
    service: PreferencesServiceDep,
) -> SettingsResponse:
    response.headers["Cache-Control"] = "no-store"
    return SettingsResponse(
        data=SettingsData(
            **asdict(
                await service.update_settings(
                    user_id, body.model_dump(exclude_unset=True)
                )
            )
        )
    )


@router.get("/login-history", response_model=HistoryResponse, dependencies=api_limit)
async def read_history(
    response: Response,
    user_id: CurrentUserIdDep,
    service: PreferencesServiceDep,
    limit: int = 10,
    offset: int = 0,
) -> HistoryResponse:
    response.headers["Cache-Control"] = "no-store"
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(422, "Invalid request")
    return HistoryResponse(
        data=HistoryData(
            **asdict(await service.get_login_history(user_id, limit, offset))
        )
    )


@router.delete(
    "",
    response_model=DeletedResponse,
    responses={**RATE_LIMIT_FAIL_CLOSED_RESPONSES, 409: {"model": ErrorResponse}},
    dependencies=[Depends(limit_by_subject(AUTH_POLICY, current_subject))],
)
async def delete_account(
    body: DeleteRequest,
    response: Response,
    identity: CurrentIdentityDep,
    service: MeServiceDep,
) -> DeletedResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        await service.delete_account(identity, body.id_token.get_secret_value())
    except (AuthenticationFailed, IdentityProviderUnavailable) as exc:
        raise auth_error(exc) from None
    except OwnershipConflict:
        raise HTTPException(
            409, "Transfer organization ownership before deleting your account"
        ) from None
    except UserNotFound:
        raise HTTPException(404, "User not found") from None
    return DeletedResponse()
