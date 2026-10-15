"""Admin stores routes through the real dependency chain, with fakes behind them."""

import asyncio
import time
from typing import Annotated

import pytest
from fastapi import Header, HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.admin import get_admin_repository
from app.api.auth import get_session_identity
from app.api.deps import get_session
from app.api.v1.admin_stores import HANDLED, _http_error, get_admin_stores_service
from app.core.firebase import VerifiedIdentity
from app.main import create_app
from app.models.platform.store import StoreStatus
from app.repositories.admin import AdminGrant
from app.services.admin_stores import (
    AdminStoreNotFound,
    AdminStoresService,
    CommitFailed,
    MigrationFailed,
    MigrationTimeout,
    StoreConflict,
)
from app.services.store_migrations import StoreMigrationFailed
from tests.fakes_admin_stores import (
    FakeAuditor,
    FakeSession,
    FakeStoresRepository,
    store,
)

KEY = "test-only-internal-service-key-not-for-deployment"
GRANTS = {
    "boss": ("super_admin", ["*"]),
    "reader": ("admin", ["stores.read"]),
    "suspender": ("admin", ["stores.suspend"]),
    "migrator": ("admin", ["stores.migrate"]),
    "other": ("admin", ["users.read"]),
}


class Harness:
    def __init__(self) -> None:
        self.repository = FakeStoresRepository(
            store("live"),
            store("held", status=StoreStatus.SUSPENDED, schema_version=2),
            store("new", status=StoreStatus.PROVISIONING),
        )
        self.session, self.auditor = FakeSession(), FakeAuditor()
        self.migrated: list[str] = []
        self.failure: Exception | None = None
        self.app = create_app()

        class Admins:
            async def get_grant(self, uid: str) -> AdminGrant | None:
                found = GRANTS.get(uid.removeprefix("uid-"))
                return AdminGrant(uid, found[0], found[1]) if found else None

        async def identity(
            x_test_uid: Annotated[str | None, Header()] = None,
        ) -> VerifiedIdentity:
            if x_test_uid is None:
                raise HTTPException(401, "Invalid authentication")
            return VerifiedIdentity(
                f"uid-{x_test_uid}", f"{x_test_uid}@example.com", True, int(time.time())
            )

        async def migrate(store_id: str) -> int:
            self.migrated.append(store_id)
            if self.failure:
                raise self.failure
            return 5

        self.app.dependency_overrides[get_session_identity] = identity
        self.app.dependency_overrides[get_admin_repository] = lambda: Admins()
        self.app.dependency_overrides[get_session] = lambda: self.session
        self.app.dependency_overrides[get_admin_stores_service] = lambda: (
            AdminStoresService(self.repository, self.session, self.auditor, migrate)
        )

    def client(self, actor: str | None = "boss") -> AsyncClient:
        headers = {"X-Internal-Key": KEY}
        if actor:
            headers["X-Test-Uid"] = actor
        transport = ASGITransport(app=self.app, raise_app_exceptions=False)
        return AsyncClient(transport=transport, base_url="http://test", headers=headers)


@pytest.fixture
def harness() -> Harness:
    return Harness()


async def test_unauthenticated_request_is_401(harness):
    async with harness.client(None) as client:
        result = await client.get("/v1/admin/stores")

    assert result.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "actor"),
    [
        ("GET", "/v1/admin/stores", "other"),
        ("GET", "/v1/admin/organizations", "other"),
        ("POST", "/v1/admin/stores/live/suspend", "reader"),
        ("POST", "/v1/admin/stores/held/unsuspend", "reader"),
        ("POST", "/v1/admin/stores/live/migrate", "suspender"),
        ("POST", "/v1/admin/stores/live/suspend", "migrator"),
        ("GET", "/v1/admin/stores", "nobody"),
    ],
)
async def test_missing_permission_is_403_and_changes_nothing(
    harness, method, path, actor
):
    async with harness.client(actor) as client:
        result = await client.request(method, path)

    assert result.status_code == 403
    assert result.json() == {"success": False, "error": "Forbidden"}
    assert harness.auditor.rows == []
    assert harness.migrated == []
    assert harness.repository.stores["live"].status is StoreStatus.ACTIVE


async def test_list_stores_returns_status_and_schema_version_without_secrets(harness):
    async with harness.client("reader") as client:
        result = await client.get("/v1/admin/stores", params={"status": "SUSPENDED"})

    body = result.json()
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert body["data"]["total_count"] == 1
    row = body["data"]["stores"][0]
    assert (row["id"], row["status"], row["schema_version"]) == ("held", "SUSPENDED", 2)
    assert set(row) == {
        "id",
        "organization_id",
        "organization_name",
        "name",
        "slug",
        "status",
        "schema_version",
        "created_at",
        "updated_at",
    }


async def test_list_organizations_returns_store_counts(harness):
    async with harness.client("reader") as client:
        result = await client.get("/v1/admin/organizations")

    data = result.json()["data"]
    assert result.status_code == 200
    assert data["organizations"][0]["store_count"] == 1
    assert (data["total_count"], data["limit"], data["offset"]) == (1, 20, 0)


@pytest.mark.parametrize(
    "query",
    [
        "status=BOGUS",
        "limit=0",
        "limit=101",
        "offset=-1",
        "organization_id=a b",
        "search=%00",
    ],
)
async def test_invalid_query_is_422(harness, query):
    async with harness.client() as client:
        result = await client.get(f"/v1/admin/stores?{query}")

    assert result.status_code == 422


async def test_suspend_then_unsuspend_round_trip_is_audited(harness):
    async with harness.client() as client:
        suspended = await client.post("/v1/admin/stores/live/suspend")
        repeated = await client.post("/v1/admin/stores/live/suspend")
        restored = await client.post("/v1/admin/stores/live/unsuspend")

    assert suspended.json()["data"] == {
        "store_id": "live",
        "status": "SUSPENDED",
        "changed": True,
    }
    assert repeated.json()["data"]["changed"] is False
    assert restored.json()["data"]["status"] == "ACTIVE"
    assert [row["action"] for row in harness.auditor.rows] == [
        "admin.stores.suspend",
        "admin.stores.unsuspend",
    ]


async def test_suspend_provisioning_store_is_409(harness):
    async with harness.client("suspender") as client:
        result = await client.post("/v1/admin/stores/new/suspend")

    assert result.status_code == 409
    assert result.json() == {
        "success": False,
        "error": "Operation not allowed in the current state",
    }


@pytest.mark.parametrize("action", ["suspend", "unsuspend", "migrate"])
async def test_unknown_store_is_404(harness, action):
    async with harness.client() as client:
        result = await client.post(f"/v1/admin/stores/nope/{action}")

    assert result.status_code == 404
    assert result.json()["error"] == "Store not found"


async def test_store_id_with_unsafe_characters_is_422(harness):
    async with harness.client() as client:
        result = await client.post("/v1/admin/stores/a$b/suspend")

    assert result.status_code == 422


async def test_migrate_returns_old_and_new_version_and_audits(harness):
    async with harness.client("migrator") as client:
        result = await client.post("/v1/admin/stores/held/migrate")

    assert result.status_code == 200
    assert result.json()["data"] == {
        "store_id": "held",
        "previous_schema_version": 2,
        "schema_version": 5,
    }
    assert harness.migrated == ["held"]
    assert harness.auditor.rows[0]["action"] == "admin.stores.migrate"


async def test_migrate_failure_is_a_generic_502_without_driver_text(harness):
    harness.failure = StoreMigrationFailed(
        "live", "OperationalError sqlstate=08006 host=db.internal"
    )
    async with harness.client("migrator") as client:
        result = await client.post("/v1/admin/stores/live/migrate")

    assert result.status_code == 502
    assert result.json() == {"success": False, "error": "Store migration failed"}
    assert "sqlstate" not in result.text
    assert harness.auditor.rows[0]["action"] == "admin.stores.migrate_failed"


async def test_migrate_provisioning_store_is_409_and_never_runs(harness):
    async with harness.client("migrator") as client:
        result = await client.post("/v1/admin/stores/new/migrate")

    assert result.status_code == 409
    assert harness.migrated == []


async def test_migration_timeout_is_503_with_retry_after(harness):
    async with harness.client("migrator") as client:
        harness.app.dependency_overrides[get_admin_stores_service] = lambda: (
            AdminStoresService(
                harness.repository, harness.session, harness.auditor, _never, 0.01
            )
        )
        result = await client.post("/v1/admin/stores/live/migrate")

    assert result.status_code == 503
    assert result.headers["retry-after"] == "30"
    assert harness.auditor.rows[0]["action"] == "admin.stores.migrate_failed"


async def _never(store_id: str) -> int:
    await asyncio.Event().wait()
    return 0


@pytest.mark.parametrize(
    ("error_type", "status", "detail", "headers"),
    [
        (AdminStoreNotFound, 404, "Store not found", None),
        (StoreConflict, 409, "Operation not allowed in the current state", None),
        (MigrationFailed, 502, "Store migration failed", None),
        (
            CommitFailed,
            503,
            "The result could not be recorded; retry",
            {"Retry-After": "5"},
        ),
        (
            MigrationTimeout,
            503,
            "Store migration did not finish in time; re-run it",
            {"Retry-After": "30"},
        ),
    ],
)
def test_each_domain_error_maps_to_its_exact_http_error(
    error_type, status, detail, headers
):
    assert error_type in HANDLED

    for raised in (error_type(), type("Sub", (error_type,), {})()):
        error = _http_error(raised)
        assert (error.status_code, error.detail, error.headers) == (
            status,
            detail,
            headers,
        )


def test_an_unmapped_error_is_a_programming_error():
    with pytest.raises(TypeError, match="unmapped"):
        _http_error(ValueError())


async def test_audit_failure_on_suspend_is_503_with_retry_after(harness):
    async def broken(*args, **kwargs):
        raise RuntimeError("audit store down")

    harness.auditor.record = broken
    async with harness.client("suspender") as client:
        result = await client.post("/v1/admin/stores/live/suspend")

    assert result.status_code == 503
    assert result.headers["retry-after"] == "5"
    assert "audit" not in result.text
    assert "cache-control" not in result.headers  # no-store is for success only


async def test_unexpected_migration_error_is_a_generic_502_and_audited(harness):
    harness.failure = RuntimeError("postgres://u:p@h/db")
    async with harness.client("migrator") as client:
        result = await client.post("/v1/admin/stores/live/migrate")

    assert result.status_code == 502
    assert "postgres" not in result.text
    assert harness.auditor.rows[0]["details"] == {"reason": "RuntimeError"}


async def test_second_migrate_while_one_is_running_is_409_and_runs_once(harness):
    started, release = asyncio.Event(), asyncio.Event()
    calls: list[str] = []

    async def slow(store_id: str) -> int:
        calls.append(store_id)
        started.set()
        await release.wait()
        return 5

    harness.app.dependency_overrides[get_admin_stores_service] = lambda: (
        AdminStoresService(harness.repository, harness.session, harness.auditor, slow)
    )
    async with harness.client("migrator") as client:
        first = asyncio.create_task(client.post("/v1/admin/stores/live/migrate"))
        await started.wait()
        second = await client.post("/v1/admin/stores/live/migrate")
        release.set()
        done = await first

    assert second.status_code == 409
    assert done.status_code == 200
    assert calls == ["live"]
