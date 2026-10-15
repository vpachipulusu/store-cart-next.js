"""End to end: the admin stores routes, repository and audit trail on a real Postgres (KAN-201).

Same contract as ``test_admin_users_e2e.py``: runs only when ``TEST_DATABASE_URL`` points
at a throwaway local database whose name ends in "_test", and rebuilds its schema with
the real Alembic migrations. Only Firebase is replaced (the session identity comes from an
``X-Test-Uid`` header) and the store-database migration, which has its own e2e suite
(``tests/services/test_store_migrations_e2e.py``) and needs a provisioned store database.
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Annotated, Any

import pytest
from fastapi import Header, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api.auth import get_session_identity
from app.api.deps import get_session_provider
from app.core.database import DefaultSessionProvider, build_engine
from app.core.firebase import VerifiedIdentity
from app.core.ids import new_id
from app.main import create_app
from app.services.store_migrations import StoreMigrationFailed

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND_ROOT = Path(__file__).resolve().parents[2]
KEY = "test-only-internal-service-key-not-for-deployment"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)


def _migrate(url: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env={**os.environ, "DATABASE_URL_DIRECT": url},
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    assert TEST_DATABASE_URL is not None
    target = make_url(TEST_DATABASE_URL)
    assert (target.database or "").endswith("_test"), (
        "refusing to rebuild a database whose name does not end in _test"
    )
    assert target.host in LOCAL_HOSTS, "refusing to rebuild a non-local database"
    _migrate(TEST_DATABASE_URL, "downgrade", "base")
    _migrate(TEST_DATABASE_URL, "upgrade", "head")
    yield TEST_DATABASE_URL


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    built = build_engine(database_url)
    async with built.begin() as connection:
        await connection.execute(
            text("TRUNCATE users, organizations, audit_logs CASCADE")
        )
    yield built
    await built.dispose()


@pytest.fixture
async def client(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    migrated: list[str] = []
    state: dict[str, Exception | None] = {"failure": None}

    async def fake_migrate(store_id: str, provider: Any) -> int:
        migrated.append(store_id)
        if state["failure"]:
            raise state["failure"]
        return 7

    monkeypatch.setattr("app.api.v1.admin_stores.migrate_store", fake_migrate)
    app = create_app()
    provider = DefaultSessionProvider(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    app.dependency_overrides[get_session_provider] = lambda: provider

    async def identity(
        x_test_uid: Annotated[str | None, Header()] = None,
    ) -> VerifiedIdentity:
        if x_test_uid is None:
            raise HTTPException(401, "Invalid authentication")
        return VerifiedIdentity(
            x_test_uid, f"{x_test_uid}@example.com", True, int(time.time())
        )

    app.dependency_overrides[get_session_identity] = identity
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-Internal-Key": KEY}
    ) as http:
        http.migrated = migrated  # type: ignore[attr-defined]
        http.state = state  # type: ignore[attr-defined]
        yield http


async def seed_admin(engine: AsyncEngine, name: str, permissions: list[str]) -> None:
    user_id = new_id()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (id, firebase_uid, email, email_verified) "
                "VALUES (:id, :uid, :email, true)"
            ),
            {"id": user_id, "uid": f"fb-{name}", "email": f"{name}@example.com"},
        )
        await connection.execute(
            text(
                "INSERT INTO admin_users (id, user_id, role, permissions) "
                "VALUES (:id, :user_id, 'admin', CAST(:perms AS jsonb))"
            ),
            {"id": new_id(), "user_id": user_id, "perms": json.dumps(permissions)},
        )


async def seed_store(
    engine: AsyncEngine,
    org_id: str,
    slug: str,
    status: str = "ACTIVE",
    version: int = 1,
) -> str:
    store_id = new_id()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO organizations (id, name, slug) VALUES (:id, :n, :s) "
                "ON CONFLICT DO NOTHING"
            ),
            {"id": org_id, "n": f"Org {org_id}", "s": f"org-{org_id}".lower()},
        )
        await connection.execute(
            text(
                "INSERT INTO stores (id, organization_id, name, slug, status, "
                "schema_version, database_ref, connection_string_encrypted) "
                "VALUES (:id, :org, :name, :slug, :status, :version, 'ref', 'secret')"
            ),
            {
                "id": store_id,
                "org": org_id,
                "name": slug.title(),
                "slug": slug,
                "status": status,
                "version": version,
            },
        )
    return store_id


async def rows(engine: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with engine.connect() as connection:
        return list((await connection.execute(text(sql), params)).all())


def as_user(name: str) -> dict[str, str]:
    return {"X-Test-Uid": f"fb-{name}", "User-Agent": "e2e-agent"}


async def test_lists_filter_by_status_organisation_and_search(client, engine):
    await seed_admin(engine, "reader", ["stores.read"])
    await seed_store(engine, "orgA", "alpha")
    await seed_store(engine, "orgA", "beta", status="SUSPENDED", version=3)
    await seed_store(engine, "orgB", "gamma")

    everything = await client.get("/v1/admin/stores", headers=as_user("reader"))
    suspended = await client.get(
        "/v1/admin/stores", params={"status": "SUSPENDED"}, headers=as_user("reader")
    )
    org_b = await client.get(
        "/v1/admin/stores",
        params={"organization_id": "orgB"},
        headers=as_user("reader"),
    )
    found = await client.get(
        "/v1/admin/stores", params={"search": "alp%"}, headers=as_user("reader")
    )
    orgs = await client.get("/v1/admin/organizations", headers=as_user("reader"))

    assert everything.json()["data"]["total_count"] == 3
    assert [s["slug"] for s in suspended.json()["data"]["stores"]] == ["beta"]
    assert suspended.json()["data"]["stores"][0]["schema_version"] == 3
    assert [s["slug"] for s in org_b.json()["data"]["stores"]] == ["gamma"]
    assert found.json()["data"]["total_count"] == 0  # a literal %, not a wildcard
    by_org = {o["id"]: o["store_count"] for o in orgs.json()["data"]["organizations"]}
    assert by_org == {"orgA": 2, "orgB": 1}
    assert "secret" not in everything.text
    assert "database_ref" not in everything.text


async def test_suspend_and_unsuspend_persist_and_write_audit_rows(client, engine):
    await seed_admin(engine, "ops", ["stores.suspend", "stores.read"])
    store_id = await seed_store(engine, "orgA", "alpha")

    suspended = await client.post(
        f"/v1/admin/stores/{store_id}/suspend", headers=as_user("ops")
    )
    again = await client.post(
        f"/v1/admin/stores/{store_id}/suspend", headers=as_user("ops")
    )
    during = await rows(engine, "SELECT status FROM stores WHERE id = :i", i=store_id)
    restored = await client.post(
        f"/v1/admin/stores/{store_id}/unsuspend", headers=as_user("ops")
    )
    after = await rows(engine, "SELECT status FROM stores WHERE id = :i", i=store_id)
    audit = await rows(
        engine,
        "SELECT action, store_id, organization_id, resource, resource_id, metadata "
        "FROM audit_logs ORDER BY created_at",
    )

    assert suspended.json()["data"]["changed"] is True
    assert again.json()["data"]["changed"] is False
    assert during[0][0] == "SUSPENDED" and after[0][0] == "ACTIVE"
    assert restored.status_code == 200
    assert [r[0] for r in audit] == ["admin.stores.suspend", "admin.stores.unsuspend"]
    assert audit[0][1:5] == (store_id, "orgA", "stores", store_id)
    assert audit[0][5]["before"] == {"status": "ACTIVE"}
    assert audit[0][5]["after"] == {"status": "SUSPENDED"}


async def test_suspended_store_is_hidden_from_the_storefront_lookup(client, engine):
    await seed_admin(engine, "ops", ["stores.suspend"])
    store_id = await seed_store(engine, "orgA", "alpha")
    await client.post(f"/v1/admin/stores/{store_id}/suspend", headers=as_user("ops"))

    found = await rows(
        engine,
        "SELECT id FROM stores WHERE slug = 'alpha' AND status = 'ACTIVE'",
    )

    assert found == []


async def test_concurrent_suspends_change_once_and_audit_once(client, engine):
    await seed_admin(engine, "ops", ["stores.suspend"])
    store_id = await seed_store(engine, "orgA", "alpha")

    results = await asyncio.gather(
        *(
            client.post(f"/v1/admin/stores/{store_id}/suspend", headers=as_user("ops"))
            for _ in range(4)
        )
    )

    assert sorted(r.json()["data"]["changed"] for r in results) == [
        False,
        False,
        False,
        True,
    ]
    assert len(await rows(engine, "SELECT 1 FROM audit_logs")) == 1


async def test_suspend_refuses_a_provisioning_store(client, engine):
    await seed_admin(engine, "ops", ["stores.suspend"])
    store_id = await seed_store(engine, "orgA", "alpha", status="PROVISIONING")

    result = await client.post(
        f"/v1/admin/stores/{store_id}/suspend", headers=as_user("ops")
    )

    assert result.status_code == 409
    assert await rows(engine, "SELECT 1 FROM audit_logs") == []


async def test_migrate_records_the_version_change_in_the_audit_trail(client, engine):
    await seed_admin(engine, "ops", ["stores.migrate"])
    store_id = await seed_store(engine, "orgA", "alpha", version=2)

    result = await client.post(
        f"/v1/admin/stores/{store_id}/migrate", headers=as_user("ops")
    )
    audit = await rows(engine, "SELECT action, metadata FROM audit_logs")

    assert result.json()["data"] == {
        "store_id": store_id,
        "previous_schema_version": 2,
        "schema_version": 7,
    }
    assert client.migrated == [store_id]  # type: ignore[attr-defined]
    assert audit[0][0] == "admin.stores.migrate"
    assert audit[0][1]["before"] == {"schema_version": 2}
    assert audit[0][1]["after"] == {"schema_version": 7}


async def test_failed_migrate_is_502_and_audited_with_a_safe_reason(client, engine):
    await seed_admin(engine, "ops", ["stores.migrate"])
    store_id = await seed_store(engine, "orgA", "alpha")
    client.state["failure"] = StoreMigrationFailed(  # type: ignore[attr-defined]
        store_id, "OperationalError sqlstate=08006"
    )

    result = await client.post(
        f"/v1/admin/stores/{store_id}/migrate", headers=as_user("ops")
    )
    audit = await rows(engine, "SELECT action, metadata FROM audit_logs")

    assert result.status_code == 502
    assert result.json()["error"] == "Store migration failed"
    assert audit[0][0] == "admin.stores.migrate_failed"
    assert audit[0][1]["details"] == {"reason": "OperationalError sqlstate=08006"}


async def test_a_permission_free_admin_gets_403_and_nothing_changes(client, engine):
    await seed_admin(engine, "nope", ["users.read"])
    store_id = await seed_store(engine, "orgA", "alpha")

    result = await client.post(
        f"/v1/admin/stores/{store_id}/suspend", headers=as_user("nope")
    )
    state = await rows(engine, "SELECT status FROM stores WHERE id = :i", i=store_id)

    assert result.status_code == 403
    assert state[0][0] == "ACTIVE"


async def test_organisations_are_paged_and_each_page_counts_its_own_stores(
    client, engine
):
    await seed_admin(engine, "reader", ["stores.read"])
    await seed_store(engine, "orgA", "a1")
    await seed_store(engine, "orgA", "a2")
    await seed_store(engine, "orgB", "b1")
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES ('orgC', 'C', 'c')")
        )

    first = await client.get(
        "/v1/admin/organizations", params={"limit": 2}, headers=as_user("reader")
    )
    second = await client.get(
        "/v1/admin/organizations",
        params={"limit": 2, "offset": 2},
        headers=as_user("reader"),
    )

    pages = [first.json()["data"], second.json()["data"]]
    assert [len(p["organizations"]) for p in pages] == [2, 1]
    assert {p["total_count"] for p in pages} == {3}
    counts = {o["id"]: o["store_count"] for p in pages for o in p["organizations"]}
    assert counts == {"orgA": 2, "orgB": 1, "orgC": 0}
    newest_first = [o["id"] for p in pages for o in p["organizations"]]
    assert newest_first == ["orgC", "orgB", "orgA"]


async def test_a_cancelled_store_session_rolls_back_and_releases_its_lock(engine):
    """What a migration timeout relies on: cancelling inside ``async with session``."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    lock_key = 5_735_701  # the migration advisory lock key

    async def hold_the_lock() -> None:
        async with maker() as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key}
            )
            await asyncio.sleep(30)

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.5):
            await hold_the_lock()

    async with engine.connect() as connection:
        free = await connection.execute(
            text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": lock_key}
        )
        assert free.scalar_one() is True
        leaked = await connection.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND pid <> pg_backend_pid() AND state LIKE 'idle in transaction%'"
            )
        )
        assert leaked.scalar_one() == 0  # the cancelled transaction was rolled back


async def test_search_treats_percent_and_underscore_literally_and_ignores_case(
    client, engine
):
    await seed_admin(engine, "reader", ["stores.read"])
    await seed_store(engine, "orgA", "a_b")
    await seed_store(engine, "orgA", "axb")
    await seed_store(engine, "orgA", "50%off")

    async def found(path: str, term: str) -> list[str]:
        result = await client.get(
            path, params={"search": term}, headers=as_user("reader")
        )
        return result.json()["data"]

    def slugs(data: dict) -> list[str]:
        return sorted(s["slug"] for s in data["stores"])

    assert slugs(await found("/v1/admin/stores", "a_b")) == ["a_b"]  # not axb
    assert slugs(await found("/v1/admin/stores", "50%")) == ["50%off"]
    assert slugs(await found("/v1/admin/stores", "A_B")) == ["a_b"]  # case-insensitive
    orgs = await found("/v1/admin/organizations", "org_")  # no org has a literal _
    assert orgs["total_count"] == 0
    orgs = await found("/v1/admin/organizations", "ORG-ORGA")  # slug, any case
    assert [o["id"] for o in orgs["organizations"]] == ["orgA"]
    assert (await found("/v1/admin/organizations", "%"))["total_count"] == 0
