"""Unit tests of the sign-in second-factor guard (KAN-257)."""

import time

import pytest
from cryptography.fernet import Fernet

from app.core.totp import TotpCodec, TotpUnavailable, generate_secret, token_at
from app.repositories.totp import TotpState
from app.services.signin_totp import SignInTotpGuard, TotpInvalid, TotpRequired

KEY = Fernet.generate_key().decode()
SECRET = generate_secret()


class Reader:
    def __init__(self, state: TotpState | None) -> None:
        self.state = state

    async def get_state(self, uid: str) -> TotpState | None:
        return self.state


def guard(state: TotpState | None) -> SignInTotpGuard:
    return SignInTotpGuard(Reader(state), lambda: TotpCodec(KEY))


def enabled(ciphertext: str | None) -> TotpState:
    return TotpState("u", True, ciphertext)


GOOD = TotpCodec(KEY).encrypt(SECRET)


@pytest.mark.parametrize(
    "state", [None, TotpState("u", False, None), TotpState("u", False, GOOD)]
)
async def test_allows_signup_and_users_without_enabled_2fa(state):
    await guard(state).check("uid", None)


@pytest.mark.parametrize("ciphertext", [None, ""])
async def test_enabled_without_secret_fails_closed(ciphertext):
    with pytest.raises(TotpUnavailable):
        await guard(enabled(ciphertext)).check("uid", "123456")


async def test_missing_code_is_required():
    with pytest.raises(TotpRequired):
        await guard(enabled(GOOD)).check("uid", None)


async def test_wrong_code_is_invalid():
    with pytest.raises(TotpInvalid):
        await guard(enabled(GOOD)).check("uid", "12345")


async def test_correct_code_passes():
    await guard(enabled(GOOD)).check("uid", token_at(SECRET, time.time()))
