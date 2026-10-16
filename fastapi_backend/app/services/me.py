from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firebase import (
    AuthenticationFailed,
    IdentityUserNotFound,
    VerifiedIdentity,
)
from app.repositories.me import ProfileData
from app.services.auth import identity_from_claims, is_recent_auth


def _sign_in_provider(claims: Mapping[str, Any]) -> object:
    firebase = claims.get("firebase")
    return firebase.get("sign_in_provider") if isinstance(firebase, dict) else None


class UserNotFound(Exception):
    pass


class OwnershipConflict(Exception):
    pass


class AccountIdentityProvider(Protocol):
    async def verify_id_token(self, token: str) -> Mapping[str, Any]: ...
    async def delete_user(self, uid: str) -> None: ...
    async def update_password(self, uid: str, password: str) -> None: ...


class ProfileRepository(Protocol):
    async def get_profile(
        self, uid: str, *, lock: bool = False
    ) -> ProfileData | None: ...
    async def update_profile(
        self, user_id: str, changes: dict[str, str | None]
    ) -> ProfileData: ...
    async def has_owner_membership(self, user_id: str) -> bool: ...
    async def delete_user(self, user_id: str) -> None: ...


class MeService:
    def __init__(
        self,
        repository: ProfileRepository,
        session: AsyncSession,
        identity: AccountIdentityProvider,
    ) -> None:
        self.repository, self.session, self.identity = repository, session, identity

    async def get_profile(self, uid: str) -> ProfileData:
        profile = await self.repository.get_profile(uid)
        if profile is None:
            raise UserNotFound()
        return profile

    async def update_profile(
        self, uid: str, changes: dict[str, str | None]
    ) -> ProfileData:
        allowed = {
            "display_name",
            "bio",
            "location",
            "website",
            "phone_number",
            "avatar_url",
        }
        if not changes or not changes.keys() <= allowed:
            raise ValueError("Invalid profile fields")
        async with self.session.begin():
            profile = await self.repository.get_profile(uid, lock=True)
            if profile is None:
                raise UserNotFound()
            return await self.repository.update_profile(profile.id, changes)

    async def _require_reauthentication(
        self, identity: VerifiedIdentity, token: str, *, password_provider: bool = False
    ) -> None:
        """The ID token the browser just minted by re-authenticating this same user.

        ``password_provider`` also requires that the re-authentication used the password
        provider, so a recent Google sign-in cannot add a password credential.
        """
        claims = await self.identity.verify_id_token(token)
        fresh = identity_from_claims(claims)
        if (
            fresh.uid != identity.uid
            or not fresh.email_verified
            or not is_recent_auth(fresh.auth_time)
        ):
            raise AuthenticationFailed()
        if password_provider and _sign_in_provider(claims) != "password":
            raise AuthenticationFailed()

    async def change_password(
        self, identity: VerifiedIdentity, token: str, new_password: str
    ) -> None:
        """Set a new password after re-authentication with the current one.

        Firebase revokes the user's refresh tokens on a password change, so other session
        cookies stop passing the revocation check (assumed from Firebase's documented
        behaviour, not exercised against live Firebase).
        """
        await self._require_reauthentication(identity, token, password_provider=True)
        async with self.session.begin():
            if await self.repository.get_profile(identity.uid) is None:
                raise UserNotFound()
        try:
            await self.identity.update_password(identity.uid, new_password)
        except IdentityUserNotFound:
            raise UserNotFound() from None

    async def delete_account(self, identity: VerifiedIdentity, token: str) -> None:
        await self._require_reauthentication(identity, token)
        async with self.session.begin():
            profile = await self.repository.get_profile(identity.uid, lock=True)
            if profile is None:
                raise UserNotFound()
            if await self.repository.has_owner_membership(profile.id):
                raise OwnershipConflict()
            # Cross-system commits cannot be atomic: fail without reporting success if SQL
            # fails after Firebase deletion. An operator must repair that residual row.
            await self.identity.delete_user(identity.uid)
            await self.repository.delete_user(profile.id)
