import time
from contextlib import asynccontextmanager

import pytest
from cryptography.fernet import Fernet

from app.core.config import settings
from app.core.firebase import AuthenticationFailed, VerifiedIdentity
from app.core.totp import TotpCodec, token_at
from app.repositories.totp import TotpState
from app.services.totp import (
    InvalidTotpCode,
    TotpConflict,
    TotpService,
    TotpUserMissing,
)


class FakeIdentity:
    def __init__(self):
        self.claims = {
            "uid": "uid",
            "email": "ada@example.com",
            "email_verified": True,
            "auth_time": int(time.time()),
        }

    async def verify_id_token(self, token):
        return self.claims


class FakeSession:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    @asynccontextmanager
    async def begin(self):
        try:
            yield self
            self.committed = True
        except Exception:
            self.rolled_back = True
            raise


class FakeRepository:
    def __init__(self):
        self.state = TotpState("user", False, None)
        self.writes = []

    async def lock_user(self, uid):
        assert uid == "uid"
        return self.state

    async def set_state(self, user_id, enabled, ciphertext):
        self.writes.append((user_id, enabled, ciphertext))
        self.state = TotpState(user_id, enabled, ciphertext)


@pytest.fixture
def setup():
    identity, repository, session = FakeIdentity(), FakeRepository(), FakeSession()
    codec = TotpCodec(Fernet.generate_key().decode())
    service = TotpService(identity, repository, session, codec)
    current = VerifiedIdentity("uid", "ada@example.com", True, int(time.time()))
    return service, current, identity, repository, session


async def test_enrollment_confirmation_and_disable_lifecycle(setup):
    service, current, _, repository, session = setup
    enrollment = await service.enroll(current, "fresh-id")
    assert session.committed
    assert repository.state.ciphertext != enrollment.secret
    assert service.codec.decrypt(repository.state.ciphertext) == enrollment.secret
    await service.confirm(current, token_at(enrollment.secret, time.time()))
    assert repository.state.enabled
    await service.disable(current, "fresh-id", token_at(enrollment.secret, time.time()))
    assert not repository.state.enabled and repository.state.ciphertext is None


async def test_reenrollment_replaces_pending_secret(setup):
    service, current, _, repository, _ = setup
    first = await service.enroll(current, "fresh-id")
    second = await service.enroll(current, "fresh-id")
    assert first.secret != second.secret
    assert service.codec.decrypt(repository.state.ciphertext) == second.secret


@pytest.mark.parametrize(
    "field,value",
    [
        ("uid", "another-user"),
        ("email_verified", False),
        ("auth_time", 0),
        ("auth_time", 9999999999),
    ],
)
async def test_fresh_identity_must_match_verified_recent_user(setup, field, value):
    service, current, identity, repository, _ = setup
    identity.claims[field] = value
    with pytest.raises(AuthenticationFailed):
        await service.enroll(current, "fresh-id")
    assert repository.writes == []


async def test_enabled_user_cannot_replace_secret(setup):
    service, current, _, repository, session = setup
    repository.state = TotpState("user", True, "existing-ciphertext")
    with pytest.raises(TotpConflict):
        await service.enroll(current, "fresh-id")
    assert repository.writes == [] and session.rolled_back


async def test_missing_user_returns_domain_error(setup):
    service, current, _, repository, _ = setup
    repository.state = None
    with pytest.raises(TotpUserMissing):
        await service.enroll(current, "fresh-id")


async def test_confirmation_requires_pending_enrollment(setup):
    service, current, _, _, _ = setup
    with pytest.raises(TotpConflict):
        await service.confirm(current, "123456")


async def test_bad_code_cannot_enable_or_disable(setup):
    service, current, _, repository, session = setup
    enrollment = await service.enroll(current, "fresh-id")
    with pytest.raises(InvalidTotpCode):
        await service.confirm(current, "abcdef")
    assert not repository.state.enabled and session.rolled_back
    await service.confirm(current, token_at(enrollment.secret, time.time()))
    with pytest.raises(InvalidTotpCode):
        await service.disable(current, "fresh-id", "abcdef")
    assert repository.state.enabled


async def test_disable_requires_enabled_state(setup):
    service, current, _, _, _ = setup
    with pytest.raises(TotpConflict):
        await service.disable(current, "fresh-id", "123456")


@pytest.mark.parametrize(
    "auth_time_offset,accepted", [(10, True), (11, False), (-300, True), (-301, False)]
)
async def test_require_recent_identity_uses_the_configured_skew(
    setup, monkeypatch, auth_time_offset, accepted
):
    monkeypatch.setattr(settings, "FIREBASE_CLOCK_SKEW_SECONDS", 10)
    monkeypatch.setattr("app.services.auth.time.time", lambda: 1_000_000.0)
    service, current, identity, _, _ = setup
    identity.claims["auth_time"] = 1_000_000 + auth_time_offset
    if accepted:
        await service.require_recent_identity(current, "fresh-id")
    else:
        with pytest.raises(AuthenticationFailed):
            await service.require_recent_identity(current, "fresh-id")
