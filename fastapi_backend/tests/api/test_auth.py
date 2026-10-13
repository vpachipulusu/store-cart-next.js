import time
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError

from app.api.auth import get_auth_service
from app.api.deps import get_rate_limiter
from app.core.config import settings
from app.core.firebase import AuthenticationFailed, IdentityProviderUnavailable
from app.main import create_app
from app.services.auth import AuthService
from tests.fakes import FakeRateLimiter, RaisingRateLimiter, as_limiter

KEY = "test-internal-key-that-is-at-least-32-chars"


class FakeIdentity:
    def __init__(self) -> None:
        self.claims: dict[str, Any] = {
            "uid": "firebase-user",
            "email": "ada@example.com",
            "email_verified": True,
            "auth_time": int(time.time()),
            "name": "Ada",
        }
        self.calls: list[str] = []
        self.failure: Exception | None = None

    async def verify_id_token(self, token: str) -> dict[str, Any]:
        self.calls.append("verify-id")
        if self.failure:
            raise self.failure
        return self.claims

    async def verify_session_cookie(self, token: str) -> dict[str, Any]:
        self.calls.append("verify-session")
        if self.failure:
            raise self.failure
        return self.claims

    async def create_session_cookie(self, token: str, expires_in: int) -> str:
        self.calls.append("mint")
        assert expires_in == 5 * 24 * 60 * 60
        return "minted-session-cookie"

    async def revoke_refresh_tokens(self, uid: str) -> None:
        self.calls.append(f"revoke:{uid}")


class FakeSession:
    def __init__(self) -> None:
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
    def __init__(self) -> None:
        self.synced: list[Any] = []
        self.history: list[tuple[str, str, str | None]] = []
        self.failure: Exception | None = None

    async def sync_user(self, identity: Any, logged_in_at: Any) -> str:
        self.synced.append(identity)
        if self.failure:
            raise self.failure
        return "platform-user"

    async def record_login(self, user_id: str, ip: str, user_agent: str | None) -> None:
        self.history.append((user_id, ip, user_agent))


@pytest.fixture
def auth_context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "BACKEND_INTERNAL_KEY", SecretStr(KEY))
    monkeypatch.setattr(
        settings,
        "BACKEND_INTERNAL_KEY_NEXT",
        SecretStr("next-internal-key-that-is-at-least-32-chars"),
    )
    identity, session, repository = FakeIdentity(), FakeSession(), FakeRepository()
    service = AuthService(identity, repository, session)
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: service
    limiter = FakeRateLimiter()
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(limiter)
    return app, identity, session, repository, limiter


def client_for(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


async def test_creates_cookie_syncs_user_and_records_login_atomically(auth_context):
    app, identity, session, repository, _ = auth_context
    async with client_for(app) as client:
        response = await client.post(
            "/v1/auth/session",
            json={"id_token": "id-token"},
            headers={
                "X-Internal-Key": KEY,
                "X-Client-IP": "192.0.2.1",
                "User-Agent": "browser",
            },
        )
    assert response.status_code == 200
    assert response.json()["data"]["session_cookie"] == "minted-session-cookie"
    assert identity.calls == ["verify-id", "mint"]
    assert session.committed
    assert repository.synced[0].uid == "firebase-user"
    assert repository.history == [("platform-user", "192.0.2.1", "browser")]
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers  # Next.js sets the browser cookie.


@pytest.mark.parametrize("key", [None, "", "wrong"])
async def test_rejects_invalid_service_key_before_provider_or_limiter(
    auth_context, key
):
    app, identity, session, repository, limiter = auth_context
    headers = {"X-Internal-Key": key} if key else {}
    async with client_for(app) as client:
        response = await client.post(
            "/v1/auth/session", json={"id_token": "id"}, headers=headers
        )
    assert response.status_code == 401
    assert not identity.calls and not repository.synced and not session.committed
    assert not limiter.hits


async def test_next_service_key_is_accepted(auth_context):
    app, *_ = auth_context
    async with client_for(app) as client:
        response = await client.post(
            "/v1/auth/session",
            json={"id_token": "id"},
            headers={"X-Internal-Key": "next-internal-key-that-is-at-least-32-chars"},
        )
    assert response.status_code == 200


@pytest.mark.parametrize("age", [301, -60])
async def test_rejects_stale_or_future_auth_time_before_minting(auth_context, age):
    app, identity, _, repository, _ = auth_context
    identity.claims["auth_time"] = int(time.time()) - age
    async with client_for(app) as client:
        response = await client.post(
            "/v1/auth/session", json={"id_token": "id"}, headers={"X-Internal-Key": KEY}
        )
    assert response.status_code == 401
    assert identity.calls == ["verify-id"] and not repository.synced


@pytest.mark.parametrize(
    "failure,status",
    [(AuthenticationFailed(), 401), (IdentityProviderUnavailable(), 503)],
)
async def test_provider_failures_are_sanitized(auth_context, failure, status):
    app, identity, *_ = auth_context
    identity.failure = failure
    async with client_for(app) as client:
        response = await client.post(
            "/v1/auth/session",
            json={"id_token": "private-token"},
            headers={"X-Internal-Key": KEY},
        )
    assert response.status_code == status
    assert response.json()["success"] is False
    assert "private-token" not in response.text


async def test_database_failure_rolls_back_without_returning_cookie(auth_context):
    app, _, session, repository, _ = auth_context
    repository.failure = RuntimeError("private-database-detail")
    async with client_for(app) as client:
        response = await client.post(
            "/v1/auth/session", json={"id_token": "id"}, headers={"X-Internal-Key": KEY}
        )
    assert response.status_code == 500
    assert session.rolled_back and not session.committed
    assert (
        "minted-session" not in response.text
        and "private-database" not in response.text
    )


async def test_auth_limiter_outage_fails_closed_before_firebase(auth_context):
    app, identity, *_ = auth_context
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(
        RaisingRateLimiter()
    )
    async with client_for(app) as client:
        response = await client.post(
            "/v1/auth/session", json={"id_token": "id"}, headers={"X-Internal-Key": KEY}
        )
    assert response.status_code == 503 and response.headers["retry-after"] == "5"
    assert not identity.calls


async def test_authenticated_request_verifies_session_and_email_claim(auth_context):
    app, identity, *_ = auth_context
    async with client_for(app) as client:
        response = await client.get(
            "/v1/auth/session",
            headers={"X-Internal-Key": KEY, "X-Session-Token": "session"},
        )
        assert response.status_code == 200
        identity.claims["email_verified"] = False
        denied = await client.get(
            "/v1/auth/session",
            headers={"X-Internal-Key": KEY, "X-Session-Token": "session"},
        )
    assert denied.status_code == 403
    assert identity.calls == ["verify-session", "verify-session"]


async def test_missing_session_is_rejected_without_firebase(auth_context):
    app, identity, *_ = auth_context
    async with client_for(app) as client:
        response = await client.get("/v1/auth/session", headers={"X-Internal-Key": KEY})
    assert response.status_code == 401 and not identity.calls


async def test_delete_verifies_then_revokes_all_user_sessions(auth_context):
    app, identity, *_ = auth_context
    identity.claims["email_verified"] = False  # unverified users may log out.
    async with client_for(app) as client:
        response = await client.delete(
            "/v1/auth/session",
            headers={"X-Internal-Key": KEY, "X-Session-Token": "session"},
        )
    assert response.status_code == 200
    assert identity.calls == ["verify-session", "revoke:firebase-user"]


@pytest.mark.parametrize("method", ["get", "delete"])
async def test_invalid_or_revoked_session_cannot_access_or_revoke(auth_context, method):
    app, identity, *_ = auth_context
    identity.failure = AuthenticationFailed()
    async with client_for(app) as client:
        response = await getattr(client, method)(
            "/v1/auth/session",
            headers={"X-Internal-Key": KEY, "X-Session-Token": "revoked-session"},
        )
    assert response.status_code == 401
    assert identity.calls == ["verify-session"]


async def test_rotating_trusted_ips_still_limits_one_verified_email(auth_context):
    app, identity, _, _, limiter = auth_context
    async with client_for(app) as client:
        statuses = []
        for index in range(1, 7):
            response = await client.post(
                "/v1/auth/session",
                json={"id_token": "id"},
                headers={"X-Internal-Key": KEY, "X-Client-IP": f"192.0.2.{index}"},
            )
            statuses.append(response.status_code)
    assert statuses == [200] * 5 + [429]
    assert identity.calls.count("mint") == 5
    assert not any("ada@example.com" in key for key, _ in limiter.hits)


async def test_missing_email_hmac_key_fails_closed_before_cookie_creation(
    auth_context, monkeypatch
):
    app, identity, *_ = auth_context
    monkeypatch.setattr(settings, "RATE_LIMIT_EMAIL_KEY", None)
    async with client_for(app) as client:
        response = await client.post(
            "/v1/auth/session", json={"id_token": "id"}, headers={"X-Internal-Key": KEY}
        )
    assert response.status_code == 503
    assert identity.calls == ["verify-id"]


async def test_email_conflict_never_links_accounts_or_returns_a_cookie(auth_context):
    app, _, session, repository, _ = auth_context
    repository.failure = IntegrityError("private-sql", {}, Exception("private-account"))
    async with client_for(app) as client:
        response = await client.post(
            "/v1/auth/session", json={"id_token": "id"}, headers={"X-Internal-Key": KEY}
        )
    assert (
        response.status_code == 409 and response.json()["error"] == "Account conflict"
    )
    assert session.rolled_back and not session.committed
    assert not repository.history and "cookie" not in response.text


async def test_session_status_limiter_outage_fails_closed(auth_context):
    app, *_ = auth_context
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(
        RaisingRateLimiter()
    )
    async with client_for(app) as client:
        response = await client.get(
            "/v1/auth/session",
            headers={"X-Internal-Key": KEY, "X-Session-Token": "session"},
        )
    assert response.status_code == 503 and response.headers["retry-after"] == "5"
