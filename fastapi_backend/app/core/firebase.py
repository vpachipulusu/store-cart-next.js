"""Revocable Firebase identities behind an async, injectable boundary."""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from threading import Lock
from typing import Any, Protocol, cast

import firebase_admin
from firebase_admin import auth, credentials, exceptions

from app.core.config import settings


class AuthenticationFailed(Exception):
    pass


class IdentityProviderUnavailable(Exception):
    pass


@dataclass(frozen=True)
class VerifiedIdentity:
    uid: str
    email: str
    email_verified: bool
    auth_time: int
    name: str | None = None


class IdentityProvider(Protocol):
    async def verify_id_token(self, token: str) -> Mapping[str, Any]: ...
    async def verify_session_cookie(self, token: str) -> Mapping[str, Any]: ...
    async def create_session_cookie(self, token: str, expires_in: int) -> str: ...
    async def revoke_refresh_tokens(self, uid: str) -> None: ...


_app_lock = Lock()


@lru_cache(maxsize=1)
def firebase_app() -> firebase_admin.App:
    with _app_lock:
        return _initialize_firebase_app()


def _initialize_firebase_app() -> firebase_admin.App:
    project = settings.FIREBASE_ADMIN_PROJECT_ID
    email = settings.FIREBASE_ADMIN_CLIENT_EMAIL
    key = settings.FIREBASE_ADMIN_PRIVATE_KEY
    if not project or not email or not key:
        raise IdentityProviderUnavailable()
    try:
        return firebase_admin.get_app("storecart-auth")
    except ValueError:
        credential = credentials.Certificate(
            {
                "type": "service_account",
                "project_id": project,
                "client_email": email,
                "private_key": key.get_secret_value().replace("\\n", "\n"),
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
        return firebase_admin.initialize_app(
            credential, {"projectId": project}, name="storecart-auth"
        )


INVALID_CREDENTIAL_ERRORS = (
    auth.InvalidIdTokenError,
    auth.RevokedIdTokenError,
    auth.UserDisabledError,
    auth.InvalidSessionCookieError,
    auth.RevokedSessionCookieError,
    auth.UserNotFoundError,
)


class FirebaseIdentityProvider:
    """Every blocking Admin SDK call, including initialization, runs off the event loop."""

    async def verify_id_token(self, token: str) -> Mapping[str, Any]:
        def verify() -> Mapping[str, Any]:
            try:
                return cast(
                    Mapping[str, Any],
                    auth.verify_id_token(token, app=firebase_app(), check_revoked=True),
                )
            except INVALID_CREDENTIAL_ERRORS:
                raise AuthenticationFailed() from None
            except (exceptions.FirebaseError, ValueError):
                raise IdentityProviderUnavailable() from None

        return await asyncio.to_thread(verify)

    async def verify_session_cookie(self, token: str) -> Mapping[str, Any]:
        def verify() -> Mapping[str, Any]:
            try:
                return cast(
                    Mapping[str, Any],
                    auth.verify_session_cookie(
                        token, app=firebase_app(), check_revoked=True
                    ),
                )
            except INVALID_CREDENTIAL_ERRORS:
                raise AuthenticationFailed() from None
            except (exceptions.FirebaseError, ValueError):
                raise IdentityProviderUnavailable() from None

        return await asyncio.to_thread(verify)

    async def create_session_cookie(self, token: str, expires_in: int) -> str:
        def create() -> str:
            try:
                return cast(
                    str,
                    auth.create_session_cookie(
                        token,
                        expires_in=timedelta(seconds=expires_in),
                        app=firebase_app(),
                    ),
                )
            except INVALID_CREDENTIAL_ERRORS:
                raise AuthenticationFailed() from None
            except (exceptions.FirebaseError, ValueError):
                raise IdentityProviderUnavailable() from None

        return await asyncio.to_thread(create)

    async def revoke_refresh_tokens(self, uid: str) -> None:
        def revoke() -> None:
            try:
                auth.revoke_refresh_tokens(uid, app=firebase_app())
            except (exceptions.FirebaseError, ValueError):
                raise IdentityProviderUnavailable() from None

        await asyncio.to_thread(revoke)
