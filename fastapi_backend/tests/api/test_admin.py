import json
import time
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends
from httpx import ASGITransport, AsyncClient

from app.api.admin import AuditorDep, get_admin_repository, require_admin
from app.api.auth import get_session_identity
from app.api.deps import get_session
from app.core.firebase import VerifiedIdentity
from app.core.permissions import AdminContext
from app.main import create_app
from app.repositories.admin import AdminGrant

KEY = "test-only-internal-service-key-not-for-deployment"

router = APIRouter(prefix="/test-admin", tags=["test-admin"])


@router.get("/read")
async def read(admin: Annotated[AdminContext, Depends(require_admin("users.read"))]):
    return {"user_id": admin.user_id, "permissions": sorted(admin.permissions)}


@router.get("/both")
async def both(
    admin: Annotated[
        AdminContext, Depends(require_admin("users.read", "users.update"))
    ],
):
    return {"ok": True}


@router.post("/update")
async def update(
    admin: Annotated[AdminContext, Depends(require_admin("users.update"))],
    auditor: AuditorDep,
):
    await auditor.record(
        admin,
        action="admin.users.update",
        resource="users",
        resource_id="user-9",
        before={"role": "viewer", "password": "old"},
        after={"role": "editor", "password": "new"},
    )
    return {"changed": True}


class FakeAdmins:
    def __init__(self, grant):
        self.grant = grant
        self.uids = []

    async def get_grant(self, uid):
        self.uids.append(uid)
        return self.grant


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        pass


def build(grant, authenticated=True, verified=True):
    app = create_app()
    app.include_router(router)
    admins, session = FakeAdmins(grant), FakeSession()
    app.dependency_overrides[get_admin_repository] = lambda: admins
    app.dependency_overrides[get_session] = lambda: session
    if authenticated:
        app.dependency_overrides[get_session_identity] = lambda: VerifiedIdentity(
            "firebase-user", "ada@example.com", verified, int(time.time())
        )
    return app, admins, session


def client(app, **headers):
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"X-Internal-Key": KEY} | headers,
    )


def grant(role="admin", permissions=("users.read", "users.update")):
    return AdminGrant("admin-1", role, list(permissions))


async def test_admin_with_the_permission_is_allowed():
    app, admins, _ = build(grant())
    async with client(app) as http:
        result = await http.get("/test-admin/read")
    assert result.status_code == 200
    assert result.json()["user_id"] == "admin-1"
    assert admins.uids == ["firebase-user"]


async def test_admin_without_the_permission_gets_403():
    app, _, _ = build(grant(permissions=("seo.read",)))
    async with client(app) as http:
        result = await http.get("/test-admin/read")
    assert result.status_code == 403
    assert result.json() == {"success": False, "error": "Forbidden"}


async def test_every_declared_permission_is_required():
    app, _, _ = build(grant(permissions=("users.read",)))
    async with client(app) as http:
        assert (await http.get("/test-admin/both")).status_code == 403
    app, _, _ = build(grant())
    async with client(app) as http:
        assert (await http.get("/test-admin/both")).status_code == 200


async def test_user_without_an_admin_record_gets_the_same_403():
    app, _, _ = build(None)
    async with client(app) as http:
        result = await http.get("/test-admin/read")
    assert result.status_code == 403
    assert result.json() == {"success": False, "error": "Forbidden"}


@pytest.mark.parametrize("stored", [[], None, "users.read", {"users.read": 1}])
async def test_empty_or_malformed_permissions_are_denied(stored):
    app, _, _ = build(AdminGrant("admin-1", "admin", stored))
    async with client(app) as http:
        assert (await http.get("/test-admin/read")).status_code == 403


async def test_unknown_permission_strings_do_not_grant_access():
    app, _, _ = build(grant(permissions=("users.*", "users", "read")))
    async with client(app) as http:
        assert (await http.get("/test-admin/read")).status_code == 403


async def test_unauthenticated_requests_get_401_before_any_admin_lookup():
    app, admins, _ = build(grant(), authenticated=False)
    async with client(app) as http:
        no_token = await http.get("/test-admin/read")
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as http:
        no_key = await http.get("/test-admin/read", headers={"X-Session-Token": "x"})
    assert no_token.status_code == 401
    assert no_key.status_code == 401
    assert admins.uids == []


async def test_unverified_email_is_denied_even_for_an_admin():
    app, admins, _ = build(grant(), verified=False)
    async with client(app) as http:
        result = await http.get("/test-admin/read")
    assert result.status_code == 403
    assert admins.uids == []


async def test_wildcard_gives_a_super_admin_every_known_permission():
    app, _, _ = build(grant(role="super_admin", permissions=("*",)))
    async with client(app) as http:
        assert (await http.get("/test-admin/both")).status_code == 200


async def test_wildcard_on_a_plain_admin_is_denied():
    app, _, _ = build(grant(role="admin", permissions=("*",)))
    async with client(app) as http:
        assert (await http.get("/test-admin/read")).status_code == 403


async def test_caller_supplied_permissions_cannot_widen_their_own_access():
    app, _, _ = build(grant(role="admin", permissions=("seo.read",)))
    smuggled = {
        "X-Permissions": "*",
        "X-Admin-Permissions": "users.read",
        "X-Admin-Role": "super_admin",
        "X-Role": "super_admin",
    }
    async with client(app, **smuggled) as http:
        by_header = await http.get("/test-admin/read")
        by_query = await http.get(
            "/test-admin/read?permissions=*&permission=users.read&role=super_admin"
        )
        by_body = await http.post(
            "/test-admin/update",
            json={"permissions": ["*"], "role": "super_admin"},
        )
    assert (by_header.status_code, by_query.status_code, by_body.status_code) == (
        403,
        403,
        403,
    )


async def test_audit_entry_is_written_for_an_allowed_change():
    app, _, session = build(grant())
    async with client(app, **{"User-Agent": "pytest-agent"}) as http:
        result = await http.post("/test-admin/update")
    assert result.status_code == 200
    (row,) = session.added
    assert row.user_id == "admin-1"
    assert (row.action, row.resource, row.resource_id) == (
        "admin.users.update",
        "users",
        "user-9",
    )
    assert row.user_agent == "pytest-agent"
    assert row.ip_address
    assert row.metadata_["request_id"] == result.headers["X-Request-ID"]
    assert row.metadata_["actor_role"] == "admin"
    assert row.metadata_["before"]["role"] == "viewer"
    assert row.metadata_["after"]["role"] == "editor"
    assert "old" not in json.dumps(row.metadata_)
    assert "new" not in json.dumps(row.metadata_)


async def test_no_audit_entry_is_written_for_a_denied_request():
    app, _, session = build(grant(permissions=("users.read",)))
    async with client(app) as http:
        result = await http.post("/test-admin/update")
    assert result.status_code == 403
    assert session.added == []


def test_declaring_no_or_unknown_permissions_fails_at_import_time():
    with pytest.raises(ValueError):
        require_admin()
    with pytest.raises(ValueError):
        require_admin("*")
    with pytest.raises(ValueError):
        require_admin("users.reed")


async def test_failed_audit_write_aborts_the_request_before_any_commit():
    class FailingSession(FakeSession):
        def __init__(self):
            super().__init__()
            self.commits = 0

        async def flush(self):
            raise RuntimeError("audit table unavailable")

        async def commit(self):
            self.commits += 1

    app, _, _ = build(grant())
    session = FailingSession()
    app.dependency_overrides[get_session] = lambda: session
    async with client(app) as http:
        result = await http.post("/test-admin/update")
    assert result.status_code == 500
    assert session.commits == 0
