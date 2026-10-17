"""Revocable Firebase identities behind an async, injectable boundary."""

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from threading import Lock
from typing import Any, Protocol, cast

import firebase_admin
from firebase_admin import auth, credentials, exceptions

from app.core.config import settings

logger = logging.getLogger("storecart.firebase")


class AuthenticationFailed(Exception):
    pass


class IdentityProviderUnavailable(Exception):
    pass


class IdentityUserNotFound(Exception):
    pass


class IdentityPasswordRejected(Exception):
    """Firebase refused a new password (for example, it violates the password policy)."""


def _log_and_wrap_outage(operation: str, exc: Exception) -> IdentityProviderUnavailable:
    """Log why Firebase Admin failed and return the sanitized domain error.

    Records the operation, exception class and SDK code, never the message.

    The SDK text can carry tokens or key fragments, so only the class name and the
    Firebase error code (for example ``PERMISSION_DENIED``) are recorded.
    """
    code: str | None = exc.code if isinstance(exc, exceptions.FirebaseError) else None
    logger.error(
        "firebase admin unavailable: operation=%s error=%s code=%s",
        operation,
        type(exc).__name__,
        code,
    )
    return IdentityProviderUnavailable()


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
        missing = [
            name
            for name, value in (
                ("FIREBASE_ADMIN_PROJECT_ID", project),
                ("FIREBASE_ADMIN_CLIENT_EMAIL", email),
                ("FIREBASE_ADMIN_PRIVATE_KEY", key),
            )
            if not value
        ]
        logger.error(
            "firebase admin is not configured, missing: %s", ", ".join(missing)
        )
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
                    auth.verify_id_token(
                        token,
                        app=firebase_app(),
                        check_revoked=True,
                        clock_skew_seconds=settings.FIREBASE_CLOCK_SKEW_SECONDS,
                    ),
                )
            except INVALID_CREDENTIAL_ERRORS:
                raise AuthenticationFailed() from None
            except (exceptions.FirebaseError, ValueError) as exc:
                raise _log_and_wrap_outage("verify_id_token", exc) from None

        return await asyncio.to_thread(verify)

    async def verify_session_cookie(self, token: str) -> Mapping[str, Any]:
        def verify() -> Mapping[str, Any]:
            try:
                return cast(
                    Mapping[str, Any],
                    auth.verify_session_cookie(
                        token,
                        app=firebase_app(),
                        check_revoked=True,
                        clock_skew_seconds=settings.FIREBASE_CLOCK_SKEW_SECONDS,
                    ),
                )
            except INVALID_CREDENTIAL_ERRORS:
                raise AuthenticationFailed() from None
            except (exceptions.FirebaseError, ValueError) as exc:
                raise _log_and_wrap_outage("verify_session_cookie", exc) from None

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
            except (exceptions.FirebaseError, ValueError) as exc:
                raise _log_and_wrap_outage("create_session_cookie", exc) from None

        return await asyncio.to_thread(create)

    async def revoke_refresh_tokens(self, uid: str) -> None:
        def revoke() -> None:
            try:
                auth.revoke_refresh_tokens(uid, app=firebase_app())
            except (exceptions.FirebaseError, ValueError) as exc:
                raise _log_and_wrap_outage("revoke_refresh_tokens", exc) from None

        await asyncio.to_thread(revoke)

    async def set_user_disabled(self, uid: str, disabled: bool) -> None:
        def update() -> None:
            try:
                auth.update_user(uid, disabled=disabled, app=firebase_app())
            except auth.UserNotFoundError:
                raise IdentityUserNotFound() from None
            except (exceptions.FirebaseError, ValueError) as exc:
                raise _log_and_wrap_outage("set_user_disabled", exc) from None

        await asyncio.to_thread(update)

    async def update_password(self, uid: str, password: str) -> None:
        def update() -> None:
            try:
                auth.update_user(uid, password=password, app=firebase_app())
            except auth.UserNotFoundError:
                raise IdentityUserNotFound() from None
            except ValueError:
                # The SDK rejects an invalid password locally; keep its text out.
                raise IdentityPasswordRejected() from None
            except exceptions.InvalidArgumentError:
                raise IdentityPasswordRejected() from None
            except exceptions.FirebaseError as exc:
                raise _log_and_wrap_outage("update_password", exc) from None

        await asyncio.to_thread(update)

    async def delete_user(self, uid: str) -> None:
        def delete() -> None:
            try:
                auth.delete_user(uid, app=firebase_app())
            except auth.UserNotFoundError:
                # Idempotent across a Firebase success followed by a database failure.
                return
            except (exceptions.FirebaseError, ValueError) as exc:
                raise _log_and_wrap_outage("delete_user", exc) from None

        await asyncio.to_thread(delete)
