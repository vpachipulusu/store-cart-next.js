import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.firebase import AuthenticationFailed, IdentityProvider, VerifiedIdentity
from app.services.signin_totp import SignInTotpGuard

SESSION_EXPIRES_SECONDS = 5 * 24 * 60 * 60
# How recent a re-authentication (ID token auth_time) must be for sensitive actions.
REAUTH_MAX_AGE_SECONDS = 300


def is_recent_auth(auth_time: float, now: float | None = None) -> bool:
    """Whether ``auth_time`` is recent, allowing the configured clock skew.

    Recent means at most ``REAUTH_MAX_AGE_SECONDS`` old.

    A token minted moments ago can carry an ``auth_time`` slightly ahead of this
    server's clock; the same skew the Admin SDK tolerates is accepted here.
    """
    age = (time.time() if now is None else now) - auth_time
    return -settings.FIREBASE_CLOCK_SKEW_SECONDS <= age <= REAUTH_MAX_AGE_SECONDS


class AccountConflict(Exception):
    """A unique identity conflict, with no database or account details exposed."""


class AuthUserRepository(Protocol):
    async def sync_user(
        self,
        identity: VerifiedIdentity,
        logged_in_at: datetime,
        *,
        touch_login: bool = True,
    ) -> str: ...
    async def record_login(
        self, user_id: str, ip: str, user_agent: str | None
    ) -> None: ...


def identity_from_claims(claims: Mapping[str, Any]) -> VerifiedIdentity:
    uid, email, authenticated_at = (
        claims.get("uid"),
        claims.get("email"),
        claims.get("auth_time"),
    )
    if not isinstance(uid, str) or not uid or len(uid) > 128:
        raise AuthenticationFailed()
    if not isinstance(email, str) or not email or len(email) > 320:
        raise AuthenticationFailed()
    if type(authenticated_at) is not int:
        raise AuthenticationFailed()
    name = claims.get("name")
    return VerifiedIdentity(
        uid,
        email,
        claims.get("email_verified") is True,
        authenticated_at,
        name if isinstance(name, str) else None,
    )


class AuthService:
    def __init__(
        self,
        identity: IdentityProvider,
        repository: AuthUserRepository,
        session: AsyncSession,
        totp_guard: SignInTotpGuard | None = None,
    ) -> None:
        self.identity = identity
        self.repository = repository
        self.session = session
        # Wired by ``get_auth_service``; ``None`` only in tests of unrelated behaviour.
        self.totp_guard = totp_guard

    async def prepare_login(self, token: str) -> VerifiedIdentity:
        identity = identity_from_claims(await self.identity.verify_id_token(token))
        if not is_recent_auth(identity.auth_time):
            raise AuthenticationFailed()
        return identity

    async def create_session(
        self,
        token: str,
        identity: VerifiedIdentity,
        ip: str,
        user_agent: str | None,
        totp_code: str | None = None,
    ) -> str:
        # The second factor is checked before any credential is minted or login recorded (KAN-257).
        if self.totp_guard is not None:
            async with self.session.begin():
                await self.totp_guard.check(identity.uid, totp_code)
        cookie = await self.identity.create_session_cookie(
            token, SESSION_EXPIRES_SECONDS
        )
        # Never deliver the credential before both sync and login history commit.
        try:
            async with self.session.begin():
                user_id = await self.repository.sync_user(identity, datetime.now(UTC))
                await self.repository.record_login(user_id, ip, user_agent)
        except IntegrityError:
            raise AccountConflict() from None
        return cookie

    async def refresh_session(self, current: VerifiedIdentity, token: str) -> str:
        """Re-issue a session for the signed-in user from a same-UID ID token.

        No freshness check and no login history (KAN-163): this only re-syncs
        ``email_verified`` and mints a new cookie. The current session is required
        so a bare ID token can never mint one here.
        """
        fresh = identity_from_claims(await self.identity.verify_id_token(token))
        if fresh.uid != current.uid:
            raise AuthenticationFailed()
        cookie = await self.identity.create_session_cookie(
            token, SESSION_EXPIRES_SECONDS
        )
        try:
            async with self.session.begin():
                await self.repository.sync_user(
                    fresh, datetime.now(UTC), touch_login=False
                )
        except IntegrityError:
            raise AccountConflict() from None
        return cookie

    async def verify_id_token(self, token: str) -> VerifiedIdentity:
        """Signature, expiry and revocation only; no freshness, no database write."""
        return identity_from_claims(await self.identity.verify_id_token(token))

    async def authenticate(self, token: str) -> VerifiedIdentity:
        return identity_from_claims(await self.identity.verify_session_cookie(token))

    async def revoke(self, identity: VerifiedIdentity) -> None:
        # Firebase revocation invalidates every refresh token/session for this UID.
        await self.identity.revoke_refresh_tokens(identity.uid)
