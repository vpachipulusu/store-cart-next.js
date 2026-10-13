import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.firebase import (
    AuthenticationFailed,
    FirebaseIdentityProvider,
    IdentityProviderUnavailable,
    VerifiedIdentity,
)
from app.repositories.auth import AuthRepository
from app.services.auth import AuthService


def require_internal_key(
    request: Request, key: Annotated[str | None, Header(alias="X-Internal-Key")] = None
) -> None:
    configured = [
        secret.get_secret_value()
        for secret in (
            settings.BACKEND_INTERNAL_KEY,
            settings.BACKEND_INTERNAL_KEY_NEXT,
        )
        if secret
    ]
    if not configured:
        raise HTTPException(503, "Service temporarily unavailable")
    supplied = (key or "").encode()
    matches = [
        secrets.compare_digest(supplied, expected.encode()) for expected in configured
    ]
    if not any(matches):
        raise HTTPException(401, "Unauthorized")
    request.state.internal_authenticated = True


def get_auth_service(
    _internal: Annotated[None, Depends(require_internal_key)], session: SessionDep
) -> AuthService:
    return AuthService(FirebaseIdentityProvider(), AuthRepository(session), session)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def auth_error(
    exc: AuthenticationFailed | IdentityProviderUnavailable,
) -> HTTPException:
    if isinstance(exc, AuthenticationFailed):
        return HTTPException(401, "Invalid authentication")
    return HTTPException(503, "Service temporarily unavailable", {"Retry-After": "5"})


async def get_session_identity(
    _internal: Annotated[None, Depends(require_internal_key)],
    service: AuthServiceDep,
    token: Annotated[str | None, Header(alias="X-Session-Token")] = None,
) -> VerifiedIdentity:
    if not token or len(token) > 16384:
        raise HTTPException(401, "Invalid authentication")
    try:
        return await service.authenticate(token)
    except (AuthenticationFailed, IdentityProviderUnavailable) as exc:
        raise auth_error(exc) from None


SessionIdentityDep = Annotated[VerifiedIdentity, Depends(get_session_identity)]


async def get_current_identity(identity: SessionIdentityDep) -> VerifiedIdentity:
    if not identity.email_verified:
        raise HTTPException(403, "Email verification required")
    return identity
