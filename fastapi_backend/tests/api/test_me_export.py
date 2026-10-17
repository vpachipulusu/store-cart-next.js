import time
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.auth import get_current_identity
from app.api.deps import get_rate_limiter
from app.api.v1.me_export import get_export_service
from app.core.firebase import VerifiedIdentity
from app.core.rate_limit import EXPORT_POLICY
from app.main import create_app
from app.repositories.me_export import (
    AccountExport,
    ExportLogin,
    ExportMembership,
    ExportNotification,
    ExportProfile,
    ExportSettings,
)
from app.services.me_export import ExportNotAvailable
from tests.fakes import FakeRateLimiter, RaisingRateLimiter, as_limiter

KEY = "test-only-internal-service-key-not-for-deployment"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
EXPORT = AccountExport(
    ExportProfile(
        "u1",
        "ada@example.com",
        True,
        False,
        "Ada",
        None,
        None,
        None,
        None,
        None,
        NOW,
        NOW,
    ),
    ExportSettings("dark", True, "en", "UTC"),
    [ExportMembership("o1", "Org", "org", "OWNER", NOW, "pro", "active", NOW, False)],
    [ExportLogin("l1", "1.2.3.4", "UA", None, NOW, True)],
    [ExportNotification("n1", "info", "T", "M", False, None, None, None, NOW)],
)


class FakeExportService:
    def __init__(self):
        self.calls = []
        self.failure = None

    async def export(self, uid, *, ip_address, user_agent, request_id):
        self.calls.append((uid, ip_address, user_agent))
        if self.failure:
            raise self.failure
        return EXPORT


@pytest.fixture
def context():
    app = create_app()
    service, limiter = FakeExportService(), FakeRateLimiter()
    app.dependency_overrides[get_current_identity] = lambda: VerifiedIdentity(
        "firebase-user", "ada@example.com", True, int(time.time())
    )
    app.dependency_overrides[get_export_service] = lambda: service
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(limiter)
    return app, service, limiter


def client(app):
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"X-Internal-Key": KEY},
    )


async def test_export_returns_attachment_json_for_session_user(context):
    app, service, _ = context
    async with client(app) as http:
        result = await http.post("/v1/me/export")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["content-disposition"].startswith("attachment; filename=")
    data = result.json()["data"]
    assert data["profile"]["email"] == "ada@example.com"
    assert data["memberships"][0]["subscription_tier"] == "pro"
    assert data["login_history"][0]["id"] == "l1"
    assert service.calls[0][0] == "firebase-user"


async def test_export_has_no_secret_fields(context):
    async with client(context[0]) as http:
        body = (await http.post("/v1/me/export")).text
    for forbidden in ("firebase_uid", "two_factor_secret", "stripe_", "password"):
        assert forbidden not in body


async def test_export_is_rate_limited_per_user(context):
    app, _, limiter = context
    async with client(app) as http:
        codes = [
            (await http.post("/v1/me/export")).status_code
            for _ in range(EXPORT_POLICY.limit + 1)
        ]
    assert codes[:-1] == [200] * EXPORT_POLICY.limit
    assert codes[-1] == 429
    assert limiter.hits[0][0] == "me_export:user:firebase-user"


async def test_export_fails_closed_when_limiter_is_down(context):
    app, service, _ = context
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(
        RaisingRateLimiter()
    )
    async with client(app) as http:
        result = await http.post("/v1/me/export")
    assert result.status_code == 503
    assert service.calls == []


async def test_export_missing_user_is_404(context):
    app, service, _ = context
    service.failure = ExportNotAvailable()
    async with client(app) as http:
        result = await http.post("/v1/me/export")
    assert result.status_code == 404


async def test_export_requires_internal_key(context):
    async with AsyncClient(
        transport=ASGITransport(app=context[0]), base_url="http://test"
    ) as http:
        result = await http.post("/v1/me/export")
    assert result.status_code in {401, 403}
