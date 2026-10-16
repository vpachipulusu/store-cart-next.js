from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from app.core.firebase import AuthenticationFailed, IdentityProvider, VerifiedIdentity
from app.core.totp import TotpCodec, generate_secret, provisioning_uri, verify_token
from app.repositories.totp import TotpState
from app.services.auth import identity_from_claims, is_recent_auth


class TotpConflict(Exception):
    pass


class TotpUserMissing(Exception):
    pass


class InvalidTotpCode(Exception):
    pass


class TotpUserRepository(Protocol):
    async def lock_user(self, uid: str) -> TotpState | None: ...
    async def set_state(
        self, user_id: str, enabled: bool, ciphertext: str | None
    ) -> None: ...


class TransactionSession(Protocol):
    def begin(self) -> AbstractAsyncContextManager[object]: ...


@dataclass(frozen=True)
class TotpEnrollment:
    secret: str
    uri: str


class TotpService:
    def __init__(
        self,
        identity: IdentityProvider,
        repository: TotpUserRepository,
        session: TransactionSession,
        codec: TotpCodec,
    ) -> None:
        self.identity = identity
        self.repository = repository
        self.session = session
        self.codec = codec

    async def require_recent_identity(
        self, current: VerifiedIdentity, id_token: str
    ) -> None:
        fresh = identity_from_claims(await self.identity.verify_id_token(id_token))
        if (
            fresh.uid != current.uid
            or not fresh.email_verified
            or not is_recent_auth(fresh.auth_time)
        ):
            raise AuthenticationFailed()

    async def user_state(self, uid: str) -> TotpState:
        state = await self.repository.lock_user(uid)
        if state is None:
            raise TotpUserMissing()
        return state

    async def enroll(self, current: VerifiedIdentity, id_token: str) -> TotpEnrollment:
        await self.require_recent_identity(current, id_token)
        async with self.session.begin():
            state = await self.user_state(current.uid)
            if state.enabled:
                raise TotpConflict()
            secret = generate_secret()
            await self.repository.set_state(
                state.user_id, False, self.codec.encrypt(secret)
            )
        return TotpEnrollment(secret, provisioning_uri(secret, current.email))

    async def confirm(self, current: VerifiedIdentity, token: str) -> None:
        async with self.session.begin():
            state = await self.user_state(current.uid)
            if state.enabled or not state.ciphertext:
                raise TotpConflict()
            if not verify_token(self.codec.decrypt(state.ciphertext), token):
                raise InvalidTotpCode()
            await self.repository.set_state(state.user_id, True, state.ciphertext)

    async def disable(
        self, current: VerifiedIdentity, id_token: str, token: str
    ) -> None:
        await self.require_recent_identity(current, id_token)
        async with self.session.begin():
            state = await self.user_state(current.uid)
            if not state.enabled or not state.ciphertext:
                raise TotpConflict()
            if not verify_token(self.codec.decrypt(state.ciphertext), token):
                raise InvalidTotpCode()
            await self.repository.set_state(state.user_id, False, None)
