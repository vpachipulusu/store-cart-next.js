import time

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.api.auth import get_current_identity, get_session_identity
from app.api.deps import get_rate_limiter, get_session_provider
from app.api.v1.totp import get_totp_service, router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.firebase import AuthenticationFailed, VerifiedIdentity
from app.core.totp import TotpUnavailable
from app.services.totp import (
    InvalidTotpCode,
    TotpConflict,
    TotpEnrollment,
    TotpUserMissing,
)
from tests.fakes import (
    FakeRateLimiter,
    FakeSession,
    FakeSessionProvider,
    RaisingRateLimiter,
)

KEY = "test-internal-key-that-is-at-least-32-chars"


class FakeService:
    def __init__(self):
        self.calls = []
        self.failure = None

    def record(self, name):
        self.calls.append(name)
        if self.failure:
            raise self.failure

    async def enroll(self, identity, id_token):
        self.record("enroll")
        return TotpEnrollment("one-time-secret", "otpauth://one-time-secret")

    async def confirm(self, identity, token):
        self.record("verify")

    async def disable(self, identity, id_token, token):
        self.record("disable")


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(settings, "BACKEND_INTERNAL_KEY", SecretStr(KEY))
    monkeypatch.setattr(settings, "BACKEND_INTERNAL_KEY_NEXT", None)
    monkeypatch.setattr(settings, "TOTP_ENCRYPTION_KEY", None)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)
    service, limiter = FakeService(), FakeRateLimiter()
    app.dependency_overrides[get_current_identity] = lambda: VerifiedIdentity(
        "uid", "ada@example.com", True, int(time.time())
    )
    app.dependency_overrides[get_totp_service] = lambda: service
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_session_provider] = lambda: FakeSessionProvider(
        FakeSession()
    )
    return app, service, limiter


async def post(app, endpoint, body, key=KEY):
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        return await client.post(
            f"/v1/me/totp/{endpoint}", json=body, headers={"X-Internal-Key": key}
        )


async def test_secret_only_returned_on_enrollment(setup):
    app, service, limiter = setup
    enrolled = await post(app, "enroll", {"id_token": "fresh"})
    assert enrolled.status_code == 200
    assert enrolled.json()["data"]["secret"] == "one-time-secret"
    assert enrolled.headers["cache-control"] == "no-store"
    for endpoint in ["verify", "disable"]:
        response = await post(app, endpoint, {"id_token": "fresh", "token": "123456"})
        assert response.status_code == 200
        assert response.json() == {"success": True}
        assert "secret" not in response.text
    assert service.calls == ["enroll", "verify", "disable"]
    assert all(policy.fail_closed for _, policy in limiter.hits)


async def test_service_key_rejected_before_mutation(setup):
    app, service, _ = setup
    response = await post(app, "enroll", {"id_token": "fresh"}, key="wrong")
    assert response.status_code == 401 and service.calls == []


async def test_rate_limit_outage_fails_closed_before_mutation(setup):
    app, service, _ = setup
    app.dependency_overrides[get_rate_limiter] = lambda: RaisingRateLimiter()
    response = await post(app, "verify", {"token": "123456"})
    assert response.status_code == 503 and service.calls == []


async def test_repeated_attempts_are_limited(setup):
    app, service, _ = setup
    for _ in range(5):
        assert (await post(app, "verify", {"token": "123456"})).status_code == 200
    assert (await post(app, "verify", {"token": "123456"})).status_code == 429
    assert len(service.calls) == 5


@pytest.mark.parametrize(
    "failure,status",
    [
        (AuthenticationFailed(), 401),
        (TotpUnavailable(), 503),
        (TotpUserMissing(), 404),
        (InvalidTotpCode(), 400),
        (TotpConflict(), 409),
    ],
)
async def test_domain_failures_use_safe_envelope(setup, failure, status):
    app, service, _ = setup
    service.failure = failure
    response = await post(app, "verify", {"token": "123456"})
    assert response.status_code == status
    assert response.json()["success"] is False
    assert "one-time-secret" not in response.text


async def test_missing_configuration_dependency_is_fail_closed(setup):
    app, service, _ = setup
    del app.dependency_overrides[get_totp_service]
    response = await post(app, "enroll", {"id_token": "fresh"})
    assert response.status_code == 503 and service.calls == []


async def test_invalid_request_does_not_mutate(setup):
    app, service, _ = setup
    response = await post(app, "verify", {"token": "123"})
    assert response.status_code == 422 and service.calls == []


async def test_real_factory_requires_identity_before_opening_database(setup):
    app, _, _ = setup
    del app.dependency_overrides[get_totp_service]
    del app.dependency_overrides[get_current_identity]
    provider = FakeSessionProvider(FakeSession())
    app.dependency_overrides[get_session_provider] = lambda: provider
    response = await post(app, "enroll", {"id_token": "fresh"}, key="wrong")
    assert response.status_code == 401
    assert provider.opened == 0


async def test_unverified_identity_rejected_before_opening_database(setup):
    app, _, _ = setup
    del app.dependency_overrides[get_totp_service]
    del app.dependency_overrides[get_current_identity]
    app.dependency_overrides[get_session_identity] = lambda: VerifiedIdentity(
        "uid", "ada@example.com", False, int(time.time())
    )
    provider = FakeSessionProvider(FakeSession())
    app.dependency_overrides[get_session_provider] = lambda: provider
    response = await post(app, "enroll", {"id_token": "fresh"})
    assert response.status_code == 403
    assert provider.opened == 0


def test_real_factory_constructs_injected_service(setup, monkeypatch):
    from cryptography.fernet import Fernet

    _, _, _ = setup
    monkeypatch.setattr(
        settings, "TOTP_ENCRYPTION_KEY", SecretStr(Fernet.generate_key().decode())
    )
    identity = VerifiedIdentity("uid", "ada@example.com", True, int(time.time()))
    session = FakeSession()
    service = get_totp_service(identity, session)
    assert service.session is session
    assert service.repository.session is session
