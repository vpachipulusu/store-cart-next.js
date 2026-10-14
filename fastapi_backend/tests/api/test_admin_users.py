"""Admin users routes through the real dependency chain, with a fake store behind them."""

import time
from typing import Annotated

import pytest
from fastapi import Header, HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.admin import get_admin_repository
from app.api.auth import get_session_identity
from app.api.deps import get_session
from app.api.v1.admin_users import get_admin_users_service
from app.core.firebase import IdentityProviderUnavailable, VerifiedIdentity
from app.main import create_app
from app.repositories.admin import AdminGrant
from app.services.admin_users import AdminUsersService
from tests.fakes_admin_users import (
    FakeAccounts,
    FakeAuditor,
    FakeSession,
    FakeStore,
    user,
)

KEY = "test-only-internal-service-key-not-for-deployment"
MANAGER_PERMISSIONS = [
    "users.read",
    "users.update",
    "users.delete",
    "admins.create",
    "admins.delete",
]


class Harness:
    def __init__(self) -> None:
        self.store = FakeStore(
            user("sa", role="super_admin", permissions=["*"]),
            user("sa2", role="super_admin", permissions=["*"]),
            user("mgr", role="admin", permissions=MANAGER_PERMISSIONS),
            user("reader", role="admin", permissions=["users.read"]),
            user("bob"),
            user("plain"),
        )
        self.accounts, self.auditor, self.session = (
            FakeAccounts(),
            FakeAuditor(),
            FakeSession(),
        )
        self.app = create_app()
        store = self.store

        class Admins:
            async def get_grant(self, uid: str) -> AdminGrant | None:
                record = store.users.get(uid.removeprefix("uid-"))
                if record is None or record.admin_role is None:
                    return None
                return AdminGrant(
                    record.id, record.admin_role, record.admin_permissions
                )

        async def identity(
            x_test_uid: Annotated[str | None, Header()] = None,
        ) -> VerifiedIdentity:
            if x_test_uid is None:
                raise HTTPException(401, "Invalid authentication")
            return VerifiedIdentity(
                f"uid-{x_test_uid}", f"{x_test_uid}@example.com", True, int(time.time())
            )

        self.app.dependency_overrides[get_session_identity] = identity
        self.app.dependency_overrides[get_admin_repository] = lambda: Admins()
        self.app.dependency_overrides[get_session] = lambda: self.session
        self.app.dependency_overrides[get_admin_users_service] = lambda: (
            AdminUsersService(self.store, self.session, self.accounts, self.auditor)
        )

    def client(self, actor: str | None = "mgr") -> AsyncClient:
        headers = {"X-Internal-Key": KEY}
        if actor:
            headers["X-Test-Uid"] = actor
        return AsyncClient(
            transport=ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://test",
            headers=headers,
        )


@pytest.fixture
def harness() -> Harness:
    return Harness()


GRANT_BODY = {"role": "admin", "permissions": ["users.read"]}
ROUTES = [
    ("GET", "/v1/admin/users", None),
    ("GET", "/v1/admin/users/bob", None),
    ("PATCH", "/v1/admin/users/bob", {"bio": "x"}),
    ("DELETE", "/v1/admin/users/bob", None),
    ("PUT", "/v1/admin/users/bob/admin", GRANT_BODY),
    ("DELETE", "/v1/admin/users/bob/admin", None),
    ("POST", "/v1/admin/users/bob/ban", None),
    ("POST", "/v1/admin/users/bob/unban", None),
]
WRITE_ROUTES = [route for route in ROUTES if route[0] != "GET"]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_unauthenticated_requests_get_401(harness, method, path, body):
    async with harness.client(actor=None) as http:
        result = await http.request(method, path, json=body)

    assert result.status_code == 401
    assert harness.auditor.rows == []


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_non_admin_users_get_403(harness, method, path, body):
    async with harness.client("plain") as http:
        result = await http.request(method, path, json=body)

    assert result.status_code == 403
    assert result.json() == {"success": False, "error": "Forbidden"}
    assert harness.auditor.rows == [] and harness.session.commits == 0


@pytest.mark.parametrize(("method", "path", "body"), WRITE_ROUTES)
async def test_admin_missing_the_permission_gets_403(harness, method, path, body):
    # "reader" holds users.read only, so every write route is outside its grant.
    async with harness.client("reader") as http:
        result = await http.request(method, path, json=body)

    assert result.status_code == 403
    assert harness.auditor.rows == [] and harness.session.commits == 0


async def test_list_returns_a_capped_page_without_sensitive_fields(harness):
    async with harness.client() as http:
        result = await http.get("/v1/admin/users?limit=2&offset=1")

    body = result.json()
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "no-store"
    assert body["data"]["total_count"] == 6
    assert (body["data"]["limit"], body["data"]["offset"]) == (2, 1)
    assert len(body["data"]["users"]) == 2
    for secret in ("two_factor_secret", "firebase_uid", "uid-"):
        assert secret not in result.text


@pytest.mark.parametrize("query", ["limit=101", "limit=0", "offset=-1", "search="])
async def test_list_rejects_out_of_range_paging(harness, query):
    async with harness.client() as http:
        result = await http.get(f"/v1/admin/users?{query}")

    assert result.status_code == 422
    assert result.json() == {"success": False, "error": "Invalid request"}


async def test_detail_shows_effective_permissions_only(harness):
    async with harness.client() as http:
        result = await http.get("/v1/admin/users/reader")

    data = result.json()["data"]
    assert data["is_admin"] is True and data["admin_permissions"] == ["users.read"]
    assert "two_factor_secret" not in result.text


async def test_detail_of_a_missing_user_is_404(harness):
    async with harness.client() as http:
        result = await http.get("/v1/admin/users/ghost")

    assert result.status_code == 404
    assert result.json() == {"success": False, "error": "User not found"}


async def test_malformed_user_ids_are_rejected(harness):
    async with harness.client() as http:
        result = await http.get("/v1/admin/users/bad%20id%3B")

    assert result.status_code == 422


async def test_update_changes_the_profile_and_audits(harness):
    async with harness.client() as http:
        result = await http.patch("/v1/admin/users/bob", json={"bio": "Hello"})

    assert result.status_code == 200 and result.json()["data"]["bio"] == "Hello"
    assert harness.auditor.rows[0]["action"] == "admin.users.update"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"email": "x@example.com"},
        {"two_factor_secret": "x"},
        {"website": "ftp://x"},
    ],
)
async def test_update_rejects_unknown_or_invalid_fields(harness, body):
    async with harness.client() as http:
        result = await http.patch("/v1/admin/users/bob", json=body)

    assert result.status_code == 422
    assert harness.auditor.rows == []


async def test_delete_succeeds_and_conflicts_are_409(harness):
    harness.store.owners.add("plain")
    async with harness.client() as http:
        ok = await http.delete("/v1/admin/users/bob")
        owner = await http.delete("/v1/admin/users/plain")
        self_delete = await http.delete("/v1/admin/users/mgr")

    assert ok.status_code == 200
    assert owner.status_code == 409 and "ownership" in owner.json()["error"]
    assert self_delete.status_code == 409


async def test_grant_by_a_manager_succeeds_within_their_own_permissions(harness):
    async with harness.client() as http:
        result = await http.put(
            "/v1/admin/users/bob/admin",
            json={"role": "admin", "permissions": ["users.read", "users.update"]},
        )

    assert result.status_code == 200
    assert result.json()["data"] == {
        "user_id": "bob",
        "role": "admin",
        "permissions": ["users.read", "users.update"],
    }
    assert harness.auditor.rows[0]["action"] == "admin.users.grant_admin"


@pytest.mark.parametrize(
    "body",
    [
        {"role": "admin", "permissions": ["settings.write"]},
        {"role": "super_admin", "permissions": ["*"]},
    ],
)
async def test_manager_cannot_grant_beyond_their_own_permissions(harness, body):
    async with harness.client() as http:
        result = await http.put("/v1/admin/users/bob/admin", json=body)

    assert result.status_code == 403
    assert harness.store.users["bob"].admin_role is None
    assert harness.auditor.rows == []


@pytest.mark.parametrize(
    "body",
    [
        {"role": "admin", "permissions": ["*"]},
        {"role": "admin", "permissions": ["nope.nope"]},
        {"role": "admin", "permissions": []},
        {"role": "root", "permissions": ["users.read"]},
        {"role": "admin", "permissions": ["users.read"], "extra": 1},
    ],
)
async def test_grant_rejects_malformed_bodies(harness, body):
    async with harness.client("sa") as http:
        result = await http.put("/v1/admin/users/bob/admin", json=body)

    assert result.status_code == 422
    assert harness.store.users["bob"].admin_role is None


async def test_manager_cannot_escalate_themselves_to_the_wildcard(harness):
    async with harness.client() as http:
        result = await http.put(
            "/v1/admin/users/mgr/admin",
            json={"role": "super_admin", "permissions": ["*"]},
        )

    assert result.status_code == 403
    assert harness.store.users["mgr"].admin_role == "admin"
    assert harness.auditor.rows == []


async def test_revoking_oneself_is_409_and_revoking_another_admin_works(harness):
    async with harness.client("sa") as http:
        self_revoke = await http.delete("/v1/admin/users/sa/admin")
        other = await http.delete("/v1/admin/users/mgr/admin")

    assert self_revoke.status_code == 409
    assert other.status_code == 200


async def test_revoke_of_a_non_admin_is_404(harness):
    async with harness.client() as http:
        result = await http.delete("/v1/admin/users/bob/admin")

    assert result.status_code == 404


async def test_ban_and_unban_call_firebase_and_audit(harness):
    async with harness.client() as http:
        banned = await http.post("/v1/admin/users/bob/ban", json={"reason": "spam"})
        unbanned = await http.post("/v1/admin/users/bob/unban")

    assert (banned.status_code, unbanned.status_code) == (200, 200)
    assert [r["action"] for r in harness.auditor.rows] == [
        "admin.users.ban",
        "admin.users.unban",
    ]
    assert ("disable", "uid-bob", True) in harness.accounts.calls


async def test_ban_maps_firebase_outage_to_503_and_unknown_account_to_404(harness):
    harness.accounts.failure = IdentityProviderUnavailable()
    async with harness.client() as http:
        outage = await http.post("/v1/admin/users/bob/ban")
        harness.accounts.failure = None
        harness.accounts.missing = True
        missing = await http.post("/v1/admin/users/bob/ban")

    assert outage.status_code == 503 and outage.headers["Retry-After"] == "5"
    assert missing.status_code == 404
    assert harness.session.commits == 0


async def test_ban_rejects_unknown_body_fields(harness):
    async with harness.client() as http:
        result = await http.post(
            "/v1/admin/users/bob/ban", json={"reason": "x", "a": 1}
        )

    assert result.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"avatar_url": "http://insecure.example/a.png"},
        {"phone_number": "call me maybe"},
        {"website": "javascript:alert(1)"},
    ],
)
async def test_update_rejects_unsafe_urls_and_phone_numbers(harness, body):
    async with harness.client() as http:
        result = await http.patch("/v1/admin/users/bob", json=body)

    assert result.status_code == 422


async def test_update_accepts_clearing_optional_fields(harness):
    async with harness.client() as http:
        result = await http.patch(
            "/v1/admin/users/bob",
            json={
                "avatar_url": "https://img.example/a.png",
                "phone_number": "+44 20 7946 0000",
                "website": "",
            },
        )

    assert result.status_code == 200


async def test_super_admin_role_needs_exactly_the_wildcard(harness):
    async with harness.client("sa") as http:
        mixed = await http.put(
            "/v1/admin/users/bob/admin",
            json={"role": "super_admin", "permissions": ["*", "users.read"]},
        )
        narrow = await http.put(
            "/v1/admin/users/bob/admin",
            json={"role": "super_admin", "permissions": ["users.read"]},
        )

    assert (mixed.status_code, narrow.status_code) == (422, 422)
