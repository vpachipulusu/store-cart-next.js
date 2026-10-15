"""End to end: the platform admin audit log API and migration 0006 on a real Postgres (KAN-49).

Same contract as ``test_admin_users_e2e.py``: runs only when ``TEST_DATABASE_URL`` points
at a throwaway local ``*_test`` database, rebuilt with the real Alembic migrations.
Only Firebase is replaced (the session identity comes from an ``X-Test-Uid`` header).
"""

import json
import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
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

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND_ROOT = Path(__file__).resolve().parents[2]
KEY = "test-only-internal-service-key-not-for-deployment"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
URL = "/v1/admin/audit-logs"
T0 = datetime(2026, 1, 1, tzinfo=UTC)

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
async def client(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
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
        yield http


async def seed_user(
    engine: AsyncEngine, name: str, permissions: list[str] | None = None
) -> str:
    """A user (uid ``fb-<name>``); with ``permissions`` also an admin grant."""
    user_id = new_id()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (id, firebase_uid, email, email_verified) "
                "VALUES (:id, :uid, :email, true)"
            ),
            {"id": user_id, "uid": f"fb-{name}", "email": f"{name}@example.com"},
        )
        if permissions is not None:
            await connection.execute(
                text(
                    "INSERT INTO admin_users (id, user_id, role, permissions) "
                    "VALUES (:id, :user, 'admin', CAST(:perms AS jsonb))"
                ),
                {"id": new_id(), "user": user_id, "perms": json.dumps(permissions)},
            )
    return user_id


async def seed_entry(engine: AsyncEngine, minutes: int = 0, **columns: Any) -> str:
    row: dict[str, Any] = {
        "id": new_id(),
        "user_id": None,
        "organization_id": None,
        "store_id": None,
        "action": "store.update",
        "resource": "store",
        "resource_id": None,
        "metadata": json.dumps({"after": {"name": "X"}}),
        "created_at": T0 + timedelta(minutes=minutes),
        **columns,
    }
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO audit_logs (id, user_id, organization_id, store_id, "
                "action, resource, resource_id, metadata, created_at) VALUES "
                "(:id, :user_id, :organization_id, :store_id, :action, :resource, "
                ":resource_id, CAST(:metadata AS jsonb), :created_at)"
            ),
            row,
        )
    return str(row["id"])


def as_user(name: str) -> dict[str, str]:
    return {"X-Test-Uid": f"fb-{name}"}


async def count_entries(engine: AsyncEngine) -> int:
    async with engine.connect() as connection:
        result = await connection.execute(text("SELECT count(*) FROM audit_logs"))
        return int(result.scalar_one())


async def test_anonymous_gets_401(client: AsyncClient) -> None:
    assert (await client.get(URL)).status_code == 401


async def test_user_who_is_not_an_admin_gets_403_and_no_data(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    await seed_user(engine, "merchant")
    await seed_entry(engine, organization_id="o1")

    response = await client.get(URL, headers=as_user("merchant"))

    assert response.status_code == 403
    assert "o1" not in response.text


async def test_admin_without_the_audit_permission_gets_403(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    await seed_user(engine, "ops", ["users.read"])

    assert (await client.get(URL, headers=as_user("ops"))).status_code == 403


async def test_merchant_owner_cannot_read_their_own_organisations_log(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    owner = await seed_user(engine, "owner")
    org_id = new_id()
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:i, 'A', :s)"),
            {"i": org_id, "s": f"a-{org_id}"},
        )
        await connection.execute(
            text(
                "INSERT INTO memberships (id, organization_id, user_id, role) "
                "VALUES (:id, :o, :u, 'OWNER')"
            ),
            {"id": new_id(), "o": org_id, "u": owner},
        )
    await seed_entry(engine, organization_id=org_id)

    response = await client.get(
        URL, params={"organization_id": org_id}, headers=as_user("owner")
    )

    assert response.status_code == 403


async def test_admin_lists_entries_newest_first_with_every_field(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    await seed_user(engine, "root", ["audit.read"])
    await seed_entry(
        engine, 1, user_id="u1", organization_id="o1", store_id="s1", resource_id="s1"
    )
    newest = await seed_entry(engine, 5, action="org.update", resource="organization")

    response = await client.get(URL, headers=as_user("root"))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()["data"]
    assert data["total_count"] == 2
    assert (data["limit"], data["offset"]) == (50, 0)
    assert data["entries"][0]["id"] == newest
    oldest = data["entries"][1]
    assert oldest["user_id"] == "u1"
    assert oldest["organization_id"] == "o1"
    assert oldest["store_id"] == "s1"
    assert oldest["action"] == "store.update"
    assert oldest["metadata"] == {"after": {"name": "X"}}


async def test_super_admin_wildcard_can_list(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await seed_user(engine, "boss")
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO admin_users (id, user_id, role, permissions) "
                "VALUES (:id, :u, 'super_admin', CAST('[\"*\"]' AS jsonb))"
            ),
            {"id": new_id(), "u": user_id},
        )

    assert (await client.get(URL, headers=as_user("boss"))).status_code == 200


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"organization_id": "o1"}, {"a", "b"}),
        ({"store_id": "s1"}, {"a"}),
        ({"user_id": "u2"}, {"b"}),
        ({"action": "org.update"}, {"c"}),
        ({"organization_id": "o1", "action": "store.update"}, {"a", "b"}),
        ({"organization_id": "o1", "user_id": "u2", "store_id": "s2"}, {"b"}),
        ({"organization_id": "nobody"}, set()),
    ],
)
async def test_each_filter_narrows_the_list(
    client: AsyncClient,
    engine: AsyncEngine,
    params: dict[str, str],
    expected: set[str],
) -> None:
    await seed_user(engine, "root", ["audit.read"])
    ids = {
        "a": await seed_entry(
            engine, 1, user_id="u1", organization_id="o1", store_id="s1"
        ),
        "b": await seed_entry(
            engine, 2, user_id="u2", organization_id="o1", store_id="s2"
        ),
        "c": await seed_entry(
            engine, 3, user_id="u1", organization_id="o2", action="org.update"
        ),
    }

    response = await client.get(URL, params=params, headers=as_user("root"))

    data = response.json()["data"]
    assert {entry["id"] for entry in data["entries"]} == {ids[key] for key in expected}
    assert data["total_count"] == len(expected)


async def test_pagination_pages_without_overlap_and_reports_the_total(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    await seed_user(engine, "root", ["audit.read"])
    created = [await seed_entry(engine, minute) for minute in range(5)]

    pages = []
    for offset in (0, 2, 4):
        response = await client.get(
            URL, params={"limit": 2, "offset": offset}, headers=as_user("root")
        )
        pages.append(response.json()["data"])

    assert [page["total_count"] for page in pages] == [5, 5, 5]
    ordered = [entry["id"] for page in pages for entry in page["entries"]]
    assert ordered == list(reversed(created))


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"offset": 1_000_001},
        {"organization_id": "bad id!"},
        {"store_id": "x" * 200},
        {"user_id": ""},
        {"action": "Not An Action"},
    ],
)
async def test_invalid_query_is_422(
    client: AsyncClient, engine: AsyncEngine, params: dict[str, Any]
) -> None:
    await seed_user(engine, "root", ["audit.read"])

    response = await client.get(URL, params=params, headers=as_user("root"))

    assert response.status_code == 422


async def test_listing_writes_no_audit_entry(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    await seed_user(engine, "root", ["audit.read"])

    await client.get(URL, headers=as_user("root"))

    assert await count_entries(engine) == 0


async def test_admin_user_changes_stay_audited_with_the_acting_admin(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    admin_id = await seed_user(engine, "root", ["audit.read", "users.update"])
    target = await seed_user(engine, "target")

    patched = await client.patch(
        f"/v1/admin/users/{target}",
        json={"display_name": "New Name"},
        headers=as_user("root"),
    )
    listed = await client.get(
        URL, params={"user_id": admin_id}, headers=as_user("root")
    )

    assert patched.status_code == 200
    entries = listed.json()["data"]["entries"]
    assert [entry["action"] for entry in entries] == ["admin.users.update"]
    assert entries[0]["resource_id"] == target


async def _columns_and_indexes(url: str) -> tuple[set[str], set[str]]:
    engine = build_engine(url)
    try:
        async with engine.connect() as connection:
            columns = await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'audit_logs'"
                )
            )
            indexes = await connection.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'audit_logs'")
            )
            return {r[0] for r in columns}, {r[0] for r in indexes}
    finally:
        await engine.dispose()


async def test_migration_0006_adds_store_id_and_indexes_and_downgrades(
    database_url: str,
) -> None:
    columns, indexes = await _columns_and_indexes(database_url)
    assert "store_id" in columns
    assert {"ix_audit_logs_store_id_created_at", "ix_audit_logs_created_at"} <= indexes

    _migrate(database_url, "downgrade", "0005")
    columns, indexes = await _columns_and_indexes(database_url)
    assert "store_id" not in columns
    assert "ix_audit_logs_store_id_created_at" not in indexes
    assert "ix_audit_logs_created_at" not in indexes

    _migrate(database_url, "upgrade", "head")
    columns, _ = await _columns_and_indexes(database_url)
    assert "store_id" in columns
