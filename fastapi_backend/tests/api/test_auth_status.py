"""KAN-208: session status (unverified allowed) and ID-token verification routes."""

import time
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.api.auth import get_auth_service
from app.api.deps import get_rate_limiter
from app.core.config import settings
from app.core.firebase import AuthenticationFailed, IdentityProviderUnavailable
from app.core.rate_limit import API_POLICY
from app.main import create_app
from app.services.auth import AuthService
from tests.api.test_auth import FakeIdentity, FakeRepository, FakeSession, NoTotpGuard
from tests.fakes import FakeRateLimiter, RaisingRateLimiter, as_limiter

KEY = "test-internal-key-that-is-at-least-32-chars"
HEADERS = {"X-Internal-Key": KEY, "X-Session-Token": "cookie"}


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "BACKEND_INTERNAL_KEY", SecretStr(KEY))
    identity, repository = FakeIdentity(), FakeRepository()
    service = AuthService(identity, repository, FakeSession(), NoTotpGuard())  # type: ignore[arg-type]
    limiter = FakeRateLimiter()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(limiter)
    http = AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )
    return http, identity, repository, limiter, app


# ---- GET /v1/auth/session/status


async def test_status_returns_identity_for_a_verified_session(context) -> None:
    http, identity, *_ = context
    async with http:
        response = await http.get("/v1/auth/session/status", headers=HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {
            "uid": "firebase-user",
            "email": "ada@example.com",
            "email_verified": True,
        },
    }
    assert identity.calls == ["verify-session"]
    assert response.headers["cache-control"] == "no-store"


async def test_status_allows_an_unverified_session_and_reports_it(context) -> None:
    http, identity, *_ = context
    identity.claims["email_verified"] = False
    async with http:
        response = await http.get("/v1/auth/session/status", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["data"]["email_verified"] is False


@pytest.mark.parametrize("token", [None, "", "x" * 16385])
async def test_status_without_a_usable_token_is_401_before_firebase(
    context, token: str | None
) -> None:
    http, identity, *_ = context
    headers = {"X-Internal-Key": KEY} | ({"X-Session-Token": token} if token else {})
    async with http:
        response = await http.get("/v1/auth/session/status", headers=headers)

    assert response.status_code == 401
    assert identity.calls == []


async def test_status_requires_the_internal_key(context) -> None:
    http, identity, *_ = context
    async with http:
        response = await http.get(
            "/v1/auth/session/status",
            headers={"X-Session-Token": "cookie", "X-Internal-Key": "bad"},
        )

    assert response.status_code == 401 and identity.calls == []


@pytest.mark.parametrize(
    "failure,status",
    [(AuthenticationFailed(), 401), (IdentityProviderUnavailable(), 503)],
)
async def test_status_provider_failures_are_sanitized(
    context, failure: Exception, status: int
) -> None:
    http, identity, *_ = context
    identity.failure = failure
    async with http:
        response = await http.get("/v1/auth/session/status", headers=HEADERS)

    assert response.status_code == status
    assert response.json()["success"] is False


async def test_status_uses_the_per_user_api_limit_not_the_auth_limit(context) -> None:
    http, _, _, limiter, _ = context
    async with http:
        await http.get("/v1/auth/session/status", headers=HEADERS)

    assert limiter.hits == [("api:user:firebase-user", API_POLICY)]


async def test_status_limiter_outage_fails_open(context) -> None:
    http, _, _, _, app = context
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(
        RaisingRateLimiter()
    )
    async with http:
        response = await http.get("/v1/auth/session/status", headers=HEADERS)

    assert response.status_code == 200


# ---- POST /v1/auth/id-token/verify


async def test_verify_id_token_returns_the_identity_without_syncing(context) -> None:
    http, identity, repository, *_ = context
    async with http:
        response = await http.post(
            "/v1/auth/id-token/verify",
            json={"id_token": "id"},
            headers={"X-Internal-Key": KEY},
        )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "uid": "firebase-user",
        "email": "ada@example.com",
        "email_verified": True,
    }
    assert identity.calls == ["verify-id"]
    assert repository.synced == [] and repository.history == []
    assert response.headers["cache-control"] == "no-store"


async def test_verify_id_token_accepts_an_old_token(context) -> None:
    """Freshness is the session routes' job; this only checks signature and revocation."""
    http, identity, *_ = context
    identity.claims["auth_time"] = int(time.time()) - 86_400
    async with http:
        response = await http.post(
            "/v1/auth/id-token/verify",
            json={"id_token": "id"},
            headers={"X-Internal-Key": KEY},
        )

    assert response.status_code == 200


@pytest.mark.parametrize("body", [{}, {"id_token": ""}, {"id_token": "x" * 16385}])
async def test_verify_id_token_validates_input(context, body: dict[str, Any]) -> None:
    http, identity, *_ = context
    async with http:
        response = await http.post(
            "/v1/auth/id-token/verify", json=body, headers={"X-Internal-Key": KEY}
        )

    assert response.status_code == 422 and identity.calls == []


async def test_verify_id_token_requires_the_internal_key(context) -> None:
    http, identity, *_ = context
    async with http:
        response = await http.post("/v1/auth/id-token/verify", json={"id_token": "id"})

    assert response.status_code == 401 and identity.calls == []


@pytest.mark.parametrize(
    "failure,status",
    [(AuthenticationFailed(), 401), (IdentityProviderUnavailable(), 503)],
)
async def test_verify_id_token_failures_are_sanitized(
    context, failure: Exception, status: int
) -> None:
    http, identity, *_ = context
    identity.failure = failure
    async with http:
        response = await http.post(
            "/v1/auth/id-token/verify",
            json={"id_token": "private-token"},
            headers={"X-Internal-Key": KEY},
        )

    assert response.status_code == status
    assert "private-token" not in response.text


async def test_verify_id_token_is_limited_per_client_ip_with_the_api_policy(
    context,
) -> None:
    http, _, _, limiter, _ = context
    async with http:
        await http.post(
            "/v1/auth/id-token/verify",
            json={"id_token": "id"},
            headers={"X-Internal-Key": KEY, "X-Client-IP": "192.0.2.5"},
        )

    assert limiter.hits == [("api:ip:192.0.2.5", API_POLICY)]
