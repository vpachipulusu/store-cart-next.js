import logging
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
    RATE_LIMIT_RESPONSES,
    RateLimiterDep,
    RateLimitSubject,
    client_ip,
    email_digest,
    enforce_rate_limit,
    limit_auth_attempts,
    limit_by_client_ip,
    limit_by_subject,
)
from app.core.errors import (
    AuthChallengeErrorResponse,
    ErrorResponse,
    totp_invalid,
    totp_required,
)
from app.core.firebase import (
    AuthenticationFailed,
    IdentityProviderUnavailable,
    VerifiedIdentity,
)
from app.core.rate_limit import API_POLICY, AUTH_POLICY, TOTP_SIGNIN_POLICY
from app.core.totp import TotpUnavailable
from app.services.auth import SESSION_EXPIRES_SECONDS, AccountConflict
from app.services.signin_totp import TotpInvalid, TotpRequired

logger = logging.getLogger("storecart.auth")

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


class SignInRequest(SessionRequest):
    # Plain bounded text, not a 6-digit pattern: a malformed code is refused as totp_invalid (401), not 422.
    totp_code: SecretStr | None = Field(default=None, max_length=64)


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
        401: {
            "model": AuthChallengeErrorResponse,
            "description": "Invalid authentication, or a two-factor code is "
            "missing (code totp_required) or wrong (code totp_invalid)",
        },
        409: {"model": ErrorResponse, "description": "Account conflict"},
    },
    dependencies=[Depends(limit_auth_attempts())],
)
async def create_session(
    body: SignInRequest,
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
        totp_code = (
            body.totp_code.get_secret_value() if body.totp_code is not None else None
        )
        if body.totp_code is not None:
            # Counted before the check so a guess costs budget even when it is right.
            await enforce_rate_limit(
                request,
                response,
                limiter,
                TOTP_SIGNIN_POLICY,
                [f"{TOTP_SIGNIN_POLICY.scope}:user:{identity.uid}"],
            )
        cookie = await service.create_session(
            token,
            identity,
            client_ip(request),
            request.headers.get("user-agent", "")[:512] or None,
            totp_code,
        )
    except (AuthenticationFailed, IdentityProviderUnavailable) as exc:
        raise auth_error(exc) from None
    except AccountConflict:
        raise HTTPException(409, "Account conflict") from None
    except TotpRequired:
        raise totp_required() from None
    except TotpInvalid:
        raise totp_invalid() from None
    except TotpUnavailable:
        # 2FA is on but its secret or key is unusable: refuse (fail closed). Never log the code or secret.
        logger.error("two-factor secret unusable at sign-in, refusing session")
        raise HTTPException(503, "Service temporarily unavailable") from None
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


def _identity_response(identity: VerifiedIdentity) -> IdentityResponse:
    return IdentityResponse(
        data=IdentityData(
            uid=identity.uid,
            email=identity.email,
            email_verified=identity.email_verified,
        )
    )


@router.get(
    "/session/status",
    response_model=IdentityResponse,
    responses=RATE_LIMIT_RESPONSES,
    dependencies=[Depends(limit_by_subject(API_POLICY, session_subject))],
)
async def read_session_status(
    response: Response, identity: SessionIdentityDep
) -> IdentityResponse:
    """Who the session cookie belongs to, with revocation checked.

    Unlike ``GET /session`` an unverified email is allowed (``email_verified`` says
    which), and the per-user limit is the API one, so a server can call it on every
    request. Callers that need a verified email check the flag themselves.
    """
    response.headers["Cache-Control"] = "no-store"
    return _identity_response(identity)


@router.post(
    "/id-token/verify",
    response_model=IdentityResponse,
    responses=RATE_LIMIT_RESPONSES,
    dependencies=[Depends(limit_by_client_ip(API_POLICY))],
)
async def verify_id_token(
    body: SessionRequest, response: Response, service: AuthServiceDep
) -> IdentityResponse:
    """Verify a Firebase ID token (signature, expiry, revocation) and echo its identity.

    Identity only, never proof of a recent sign-in: there is no freshness check and
    nothing is written (sign-in and refresh keep their own checks), and an unverified
    email is returned with ``email_verified`` false for the caller to act on.
    """
    response.headers["Cache-Control"] = "no-store"
    try:
        identity = await service.verify_id_token(body.id_token.get_secret_value())
    except (AuthenticationFailed, IdentityProviderUnavailable) as exc:
        raise auth_error(exc) from None
    return _identity_response(identity)
