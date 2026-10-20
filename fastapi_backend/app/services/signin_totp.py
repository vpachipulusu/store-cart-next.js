"""Second factor at sign-in (KAN-257): no session is minted for a 2FA user without a valid code."""

from collections.abc import Callable
from typing import Protocol

from app.core.totp import TotpCodec, TotpUnavailable, verify_token
from app.repositories.totp import TotpState


class TotpRequired(Exception):
    """2FA is enabled and no code was sent."""


class TotpInvalid(Exception):
    """A code was sent and it is wrong or malformed."""


class TotpStateReader(Protocol):
    async def get_state(self, uid: str) -> TotpState | None: ...


class SignInTotpGuard:
    def __init__(
        self, reader: TotpStateReader, codec_factory: Callable[[], TotpCodec]
    ) -> None:
        self.reader = reader
        # Built lazily: a deployment without a TOTP key still signs in users who have no 2FA.
        self.codec_factory = codec_factory

    async def check(self, uid: str, code: str | None) -> None:
        """Return only when sign-in may proceed. Fails closed on any unusable secret."""
        state = await self.reader.get_state(uid)
        if state is None or not state.enabled:
            return  # signup (no user row yet) or 2FA not enabled
        if not state.ciphertext:
            raise TotpUnavailable()
        if code is None:
            raise TotpRequired()
        secret = self.codec_factory().decrypt(state.ciphertext)
        if not verify_token(secret, code):
            raise TotpInvalid()
