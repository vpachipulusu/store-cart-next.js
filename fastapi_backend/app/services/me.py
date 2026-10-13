import time
from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firebase import AuthenticationFailed, VerifiedIdentity
from app.repositories.me import ProfileData
from app.services.auth import identity_from_claims


class UserNotFound(Exception):
    pass


class OwnershipConflict(Exception):
    pass


class AccountIdentityProvider(Protocol):
    async def verify_id_token(self, token: str) -> Mapping[str, Any]: ...
    async def delete_user(self, uid: str) -> None: ...


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

    async def delete_account(self, identity: VerifiedIdentity, token: str) -> None:
        fresh = identity_from_claims(await self.identity.verify_id_token(token))
        if (
            fresh.uid != identity.uid
            or not fresh.email_verified
            or not 0 <= time.time() - fresh.auth_time <= 300
        ):
            raise AuthenticationFailed()
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
