from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr

from app.api.auth import (
    AuthServiceDep,
    SessionIdentityDep,
    auth_error,
    get_current_identity,
    require_internal_key,
)
from app.api.rate_limit import (
    RATE_LIMIT_FAIL_CLOSED_RESPONSES,
    RateLimiterDep,
    RateLimitSubject,
    client_ip,
    email_digest,
    enforce_rate_limit,
    limit_auth_attempts,
    limit_by_subject,
)
from app.core.errors import ErrorResponse
from app.core.firebase import (
    AuthenticationFailed,
    IdentityProviderUnavailable,
    VerifiedIdentity,
)
from app.core.rate_limit import AUTH_POLICY
from app.services.auth import SESSION_EXPIRES_SECONDS, AccountConflict

router = APIRouter(
    prefix="/v1/auth",
    tags=["auth"],
    dependencies=[Depends(require_internal_key)],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)


class SessionRequest(BaseModel):
    id_token: SecretStr = Field(min_length=1, max_length=16384)


class SessionData(BaseModel):
    session_cookie: str
    expires_in: int


class SessionResponse(BaseModel):
    success: Literal[True] = True
    data: SessionData


class IdentityData(BaseModel):
    uid: str
    email: str
    email_verified: bool


class IdentityResponse(BaseModel):
    success: Literal[True] = True
    data: IdentityData


class RevokedResponse(BaseModel):
    success: Literal[True] = True


async def current_subject(
    identity: Annotated[VerifiedIdentity, Depends(get_current_identity)],
) -> RateLimitSubject:
    return RateLimitSubject("user", identity.uid)


@router.post(
    "/session",
    response_model=SessionResponse,
    responses={
        **RATE_LIMIT_FAIL_CLOSED_RESPONSES,
        409: {"model": ErrorResponse, "description": "Account conflict"},
    },
    dependencies=[Depends(limit_auth_attempts())],
)
async def create_session(
    body: SessionRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
    limiter: RateLimiterDep,
) -> SessionResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        token = body.id_token.get_secret_value()
        identity = await service.prepare_login(token)
        await enforce_rate_limit(
            request,
            response,
            limiter,
            AUTH_POLICY,
            [f"{AUTH_POLICY.scope}:email:{email_digest(identity.email)}"],
        )
        cookie = await service.create_session(
            token,
            identity,
            client_ip(request),
            request.headers.get("user-agent", "")[:512] or None,
        )
    except (AuthenticationFailed, IdentityProviderUnavailable) as exc:
        raise auth_error(exc) from None
    except AccountConflict:
        raise HTTPException(409, "Account conflict") from None
    return SessionResponse(
        data=SessionData(session_cookie=cookie, expires_in=SESSION_EXPIRES_SECONDS)
    )


async def session_subject(identity: SessionIdentityDep) -> RateLimitSubject:
    # Refresh must work for a not-yet-verified session (that is what it re-syncs).
    return RateLimitSubject("user", identity.uid)


@router.post(
    "/session/refresh",
    response_model=SessionResponse,
    responses={
        **RATE_LIMIT_FAIL_CLOSED_RESPONSES,
        409: {"model": ErrorResponse, "description": "Account conflict"},
    },
    dependencies=[Depends(limit_by_subject(AUTH_POLICY, session_subject))],
)
async def refresh_session(
    body: SessionRequest,
    response: Response,
    service: AuthServiceDep,
    identity: SessionIdentityDep,
) -> SessionResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        cookie = await service.refresh_session(
            identity, body.id_token.get_secret_value()
        )
    except (AuthenticationFailed, IdentityProviderUnavailable) as exc:
        raise auth_error(exc) from None
    except AccountConflict:
        raise HTTPException(409, "Account conflict") from None
    return SessionResponse(
        data=SessionData(session_cookie=cookie, expires_in=SESSION_EXPIRES_SECONDS)
    )


@router.get(
    "/session",
    response_model=IdentityResponse,
    responses=RATE_LIMIT_FAIL_CLOSED_RESPONSES,
    dependencies=[Depends(limit_by_subject(AUTH_POLICY, current_subject))],
)
async def read_session(
    response: Response,
    identity: Annotated[VerifiedIdentity, Depends(get_current_identity)],
) -> IdentityResponse:
    response.headers["Cache-Control"] = "no-store"
    return IdentityResponse(
        data=IdentityData(
            uid=identity.uid,
            email=identity.email,
            email_verified=identity.email_verified,
        )
    )


@router.delete(
    "/session",
    response_model=RevokedResponse,
    responses=RATE_LIMIT_FAIL_CLOSED_RESPONSES,
    dependencies=[Depends(limit_auth_attempts())],
)
async def delete_session(
    response: Response, service: AuthServiceDep, identity: SessionIdentityDep
) -> RevokedResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        await service.revoke(identity)
    except (AuthenticationFailed, IdentityProviderUnavailable) as exc:
        raise auth_error(exc) from None
    return RevokedResponse()
