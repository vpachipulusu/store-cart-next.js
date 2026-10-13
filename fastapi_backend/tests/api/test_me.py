import time
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.auth import get_current_identity
from app.api.deps import get_rate_limiter
from app.api.me import get_me_service, get_preferences_service
from app.core.firebase import (
    AuthenticationFailed,
    IdentityProviderUnavailable,
    VerifiedIdentity,
)
from app.main import create_app
from app.repositories.me import ProfileData
from app.repositories.me_preferences import HistoryEntry, HistoryPage, SettingsData
from app.services.me import OwnershipConflict, UserNotFound
from tests.fakes import FakeRateLimiter, RaisingRateLimiter, as_limiter

KEY = "test-only-internal-service-key-not-for-deployment"
PROFILE = ProfileData(
    "platform-user",
    "ada@example.com",
    True,
    "Ada",
    None,
    None,
    None,
    None,
    None,
    datetime(2026, 1, 1, tzinfo=UTC),
)


class FakeMe:
    def __init__(self):
        self.profile = PROFILE
        self.failure = None
        self.uids = []
        self.changes = []
        self.deleted = []

    async def get_profile(self, uid):
        self.uids.append(uid)
        if self.failure:
            raise self.failure
        return self.profile

    async def update_profile(self, uid, changes):
        await self.get_profile(uid)
        self.changes.append(changes)
        self.profile = replace(self.profile, **changes)
        return self.profile

    async def delete_account(self, identity, token):
        if self.failure:
            raise self.failure
        self.deleted.append((identity.uid, token))


class FakePreferences:
    def __init__(self):
        self.calls = []
        self.settings = SettingsData("system", True, "en", "UTC")

    async def get_settings(self, user_id):
        self.calls.append((user_id,))
        return self.settings

    async def update_settings(self, user_id, changes):
        self.calls.append((user_id, changes))
        self.settings = replace(self.settings, **changes)
        return self.settings

    async def get_login_history(self, user_id, limit, offset):
        self.calls.append((user_id, limit, offset))
        return HistoryPage(
            [
                HistoryEntry(
                    "login-1",
                    "127.0.0.1",
                    None,
                    None,
                    datetime(2026, 1, 1, tzinfo=UTC),
                    True,
                )
            ],
            1,
        )


@pytest.fixture
def context():
    app = create_app()
    me, preferences, limiter = FakeMe(), FakePreferences(), FakeRateLimiter()
    app.dependency_overrides[get_current_identity] = lambda: VerifiedIdentity(
        "firebase-user", "ada@example.com", True, int(time.time())
    )
    app.dependency_overrides[get_me_service] = lambda: me
    app.dependency_overrides[get_preferences_service] = lambda: preferences
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(limiter)
    return app, me, preferences, limiter


def client(app):
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"X-Internal-Key": KEY},
    )


async def test_profile_has_only_safe_fields_and_uses_session_uid(context):
    app, me, _, _ = context
    async with client(app) as http:
        result = await http.get("/v1/me")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["data"]["id"] == "platform-user"
    assert me.uids == ["firebase-user"]
    assert set(result.json()["data"]) == set(PROFILE.__dataclass_fields__)


async def test_profile_patch_preserves_omitted_fields_and_clears_explicit_null(context):
    app, me, _, _ = context
    async with client(app) as http:
        result = await http.patch("/v1/me", json={"bio": "Hello", "website": ""})
    assert result.status_code == 200
    assert me.changes == [{"bio": "Hello", "website": None}]
    assert result.json()["data"]["display_name"] == "Ada"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"email": "other@example.com"},
        {"two_factor_secret": "secret"},
        {"display_name": "x" * 101},
        {"bio": "x" * 501},
        {"phone_number": "x" * 21},
        {"website": "javascript:alert(1)"},
        {"website": "https://user:pass@example.com"},
    ],
)
async def test_profile_rejects_unsafe_or_invalid_edits(context, body):
    app, me, _, _ = context
    async with client(app) as http:
        result = await http.patch("/v1/me", json=body)
    assert result.status_code == 422
    assert me.changes == []


@pytest.mark.parametrize("value", ["https://example.com/avatar.png", None])
async def test_avatar_updates_or_clears_only_url_metadata(context, value):
    app, me, _, _ = context
    async with client(app) as http:
        result = await http.patch("/v1/me/avatar", json={"avatar_url": value})
    assert result.status_code == 200
    assert me.changes == [{"avatar_url": value}]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"avatar_url": "http://example.com/x"},
        {"avatar_url": "https://a:b@example.com"},
        {"avatar_url": "data:image/png;base64,x"},
        {"avatar_url": "x" * 2049},
    ],
)
async def test_avatar_rejects_invalid_metadata(context, body):
    async with client(context[0]) as http:
        assert (await http.patch("/v1/me/avatar", json=body)).status_code == 422


async def test_settings_get_and_patch_use_platform_id_not_request_id(context):
    app, _, preferences, _ = context
    async with client(app) as http:
        read = await http.get("/v1/me/settings")
        updated = await http.patch("/v1/me/settings", json={"theme": "dark"})
    assert read.json()["data"] == {
        "theme": "system",
        "email_notifications": True,
        "language": "en",
        "timezone": "UTC",
    }
    assert updated.json()["data"]["theme"] == "dark"
    assert preferences.calls == [
        ("platform-user",),
        ("platform-user", {"theme": "dark"}),
    ]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"theme": None},
        {"theme": "bad"},
        {"email_notifications": "true"},
        {"language": "x"},
        {"timezone": ""},
        {"user_id": "other"},
    ],
)
async def test_settings_reject_invalid_or_foreign_fields(context, body):
    async with client(context[0]) as http:
        assert (await http.patch("/v1/me/settings", json=body)).status_code == 422


async def test_history_returns_scoped_page_and_total(context):
    app, _, preferences, _ = context
    async with client(app) as http:
        result = await http.get("/v1/me/login-history?limit=20&offset=10")
    assert result.status_code == 200
    assert result.json()["data"]["total_count"] == 1
    assert preferences.calls == [("platform-user", 20, 10)]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=wrong"])
async def test_history_rejects_unbounded_pagination(context, query):
    async with client(context[0]) as http:
        assert (await http.get("/v1/me/login-history?" + query)).status_code == 422


async def test_account_deletion_passes_authenticated_uid_and_fresh_token(context):
    app, me, _, _ = context
    async with client(app) as http:
        result = await http.request("DELETE", "/v1/me", json={"id_token": "fresh"})
    assert result.status_code == 200
    assert me.deleted == [("firebase-user", "fresh")]


@pytest.mark.parametrize(
    "failure,status",
    [
        (OwnershipConflict(), 409),
        (UserNotFound(), 404),
        (AuthenticationFailed(), 401),
        (IdentityProviderUnavailable(), 503),
        (RuntimeError("private secret"), 500),
    ],
)
async def test_deletion_failures_are_safe_and_never_success(context, failure, status):
    app, me, _, _ = context
    me.failure = failure
    async with client(app) as http:
        result = await http.request("DELETE", "/v1/me", json={"id_token": "fresh"})
    assert result.status_code == status
    assert result.json()["success"] is False
    assert "private secret" not in result.text
    assert not me.deleted


@pytest.mark.parametrize(
    "path,method,body",
    [
        ("/v1/me", "GET", None),
        ("/v1/me", "PATCH", {"bio": "a"}),
        ("/v1/me/avatar", "PATCH", {"avatar_url": None}),
        ("/v1/me/settings", "GET", None),
        ("/v1/me/settings", "PATCH", {"theme": "dark"}),
        ("/v1/me/login-history", "GET", None),
        ("/v1/me", "DELETE", {"id_token": "fresh"}),
    ],
)
async def test_every_endpoint_rejects_invalid_internal_key(context, path, method, body):
    async with client(context[0]) as http:
        result = await http.request(
            method, path, json=body, headers={"X-Internal-Key": "bad"}
        )
    assert result.status_code == 401


@pytest.mark.parametrize("status", [401, 403])
async def test_session_and_email_verification_fail_before_user_access(context, status):
    app, me, _, _ = context

    def denied():
        raise HTTPException(status, "Denied")

    app.dependency_overrides[get_current_identity] = denied
    async with client(app) as http:
        result = await http.get("/v1/me")
    assert result.status_code == status
    assert not me.uids


async def test_deletion_fails_closed_when_rate_limiter_is_unavailable(context):
    app, me, _, _ = context
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(
        RaisingRateLimiter()
    )
    async with client(app) as http:
        result = await http.request("DELETE", "/v1/me", json={"id_token": "fresh"})
    assert result.status_code == 503
    assert not me.deleted


@pytest.mark.parametrize("path", ["/v1/me", "/v1/me/avatar"])
async def test_profile_and_avatar_missing_user_returns_404(context, path):
    app, me, _, _ = context
    me.failure = UserNotFound()
    async with client(app) as http:
        result = await http.patch(
            path, json={"bio": "x"} if path == "/v1/me" else {"avatar_url": None}
        )
    assert result.status_code == 404


async def test_missing_profile_prevents_settings_and_history_access(context):
    app, me, preferences, _ = context
    me.failure = UserNotFound()
    async with client(app) as http:
        assert (await http.get("/v1/me")).status_code == 404
        assert (await http.get("/v1/me/settings")).status_code == 404
        assert (await http.get("/v1/me/login-history")).status_code == 404
    assert not preferences.calls
