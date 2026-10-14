"""End to end: ``require_merchant`` on a real Postgres through real HTTP routes.

Same contract as ``test_org_billing_e2e.py``: runs only when ``TEST_DATABASE_URL``
points at a throwaway local database whose name ends in "_test", and rebuilds its
schema with the real Alembic migrations. Only Firebase (the session identity comes from
an ``X-Test-Uid`` header) is replaced; the internal key check, the join query, role
and status rules and the error envelope are the production code.
"""

import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends, Header, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api.auth import get_session_identity, require_internal_key
from app.api.deps import get_session_provider
from app.api.merchant import OWNER_ADMIN, require_merchant
from app.core.database import DefaultSessionProvider, build_engine
from app.core.firebase import VerifiedIdentity
from app.core.ids import new_id
from app.main import create_app
from app.repositories.merchant import MerchantAccess

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND_ROOT = Path(__file__).resolve().parents[2]
KEY = "test-only-internal-service-key-not-for-deployment"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)

router = APIRouter(
    prefix="/v1/test-stores/{store_id}",
    tags=["test-stores"],
    dependencies=[Depends(require_internal_key)],
)


@router.get("/info")
async def info(
    merchant: Annotated[MerchantAccess, Depends(require_merchant())],
) -> dict[str, str]:
    return {
        "user_id": merchant.user_id,
        "organization_id": merchant.organization.id,
        "store_id": merchant.store.id,
        "role": merchant.role.value,
    }


@router.get("/manage")
async def manage(
    merchant: Annotated[MerchantAccess, Depends(require_merchant(OWNER_ADMIN))],
) -> dict[str, bool]:
    return {"ok": True}


@router.post("/change")
async def change(
    merchant: Annotated[MerchantAccess, Depends(require_merchant(write=True))],
) -> dict[str, bool]:
    return {"ok": True}


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
        await connection.execute(text("TRUNCATE users, organizations CASCADE"))
    yield built
    await built.dispose()


@pytest.fixture
async def client(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.include_router(router)
    provider = DefaultSessionProvider(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    app.dependency_overrides[get_session_provider] = lambda: provider

    async def identity(
        x_test_uid: Annotated[str | None, Header()] = None,
        x_test_verified: Annotated[str, Header()] = "yes",
    ) -> VerifiedIdentity:
        if x_test_uid is None:
            raise HTTPException(401, "Invalid authentication")
        return VerifiedIdentity(
            x_test_uid,
            f"{x_test_uid}@example.com",
            x_test_verified == "yes",
            int(time.time()),
        )

    app.dependency_overrides[get_session_identity] = identity
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-Internal-Key": KEY}
    ) as http:
        yield http


async def seed_org(
    engine: AsyncEngine,
    name: str,
    members: dict[str, str],
    stores: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    """Insert an organisation, members ``{user: role}`` (uid ``fb-<user>``) and stores ``{name: status}``."""
    org_id = new_id()
    store_ids = {store: new_id() for store in (stores or {})}
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:id, :n, :s)"),
            {"id": org_id, "n": name.title(), "s": f"{name}-{org_id}"},
        )
        for user, role in members.items():
            found = (
                await connection.execute(
                    text("SELECT id FROM users WHERE firebase_uid = :uid"),
                    {"uid": f"fb-{user}"},
                )
            ).scalar_one_or_none()
            user_id = found or new_id()
            if not found:
                await connection.execute(
                    text(
                        "INSERT INTO users (id, firebase_uid, email, email_verified) "
                        "VALUES (:id, :uid, :email, true)"
                    ),
                    {
                        "id": user_id,
                        "uid": f"fb-{user}",
                        "email": f"{user}@example.com",
                    },
                )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (:id, :org, :user, :role)"
                ),
                {"id": new_id(), "org": org_id, "user": user_id, "role": role},
            )
        for store, status in (stores or {}).items():
            await connection.execute(
                text(
                    "INSERT INTO stores (id, organization_id, name, slug, status) "
                    "VALUES (:id, :org, :name, :slug, :status)"
                ),
                {
                    "id": store_ids[store],
                    "org": org_id,
                    "name": store.title(),
                    "slug": f"{store}-{store_ids[store]}",
                    "status": status,
                },
            )
    return org_id, store_ids


def as_user(name: str, **extra: str) -> dict[str, str]:
    return {"X-Test-Uid": f"fb-{name}", **extra}


async def test_member_gets_user_organisation_store_and_role(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    org, stores = await seed_org(
        engine, "acme", {"alice": "OWNER", "sam": "STAFF"}, {"shop": "ACTIVE"}
    )

    result = await client.get(
        f"/v1/test-stores/{stores['shop']}/info", headers=as_user("sam")
    )

    assert result.status_code == 200
    data: dict[str, Any] = result.json()
    assert data["organization_id"] == org
    assert data["store_id"] == stores["shop"]
    assert data["role"] == "STAFF"
    assert data["user_id"]


async def test_other_organisation_unknown_store_and_non_member_are_identical_404s(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    _, a_stores = await seed_org(engine, "orga", {"alice": "OWNER"}, {"shop": "ACTIVE"})
    await seed_org(engine, "orgb", {"bob": "OWNER"}, {"shop": "ACTIVE"})
    other_store = a_stores["shop"]

    cross_org = await client.get(
        f"/v1/test-stores/{other_store}/info", headers=as_user("bob")
    )
    unknown = await client.get(
        f"/v1/test-stores/{new_id()}/info", headers=as_user("bob")
    )
    no_user_row = await client.get(
        f"/v1/test-stores/{other_store}/info", headers=as_user("ghost")
    )
    cross_org_manage = await client.get(
        f"/v1/test-stores/{other_store}/manage", headers=as_user("bob")
    )
    cross_org_write = await client.post(
        f"/v1/test-stores/{other_store}/change", headers=as_user("bob")
    )

    assert [
        r.status_code
        for r in (cross_org, unknown, no_user_row, cross_org_manage, cross_org_write)
    ] == [404] * 5
    same = (cross_org, unknown, no_user_row, cross_org_manage, cross_org_write)
    assert {r.content for r in same} == {b'{"success":false,"error":"Store not found"}'}
    assert (
        len(
            {
                tuple(
                    sorted(
                        (k, v)
                        for k, v in r.headers.items()
                        if k not in ("x-request-id",)
                    )
                )
                for r in same
            }
        )
        == 1
    )


async def test_role_is_read_from_the_membership_table_on_each_request(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    _, stores = await seed_org(
        engine, "acme", {"alice": "OWNER", "adam": "ADMIN"}, {"shop": "ACTIVE"}
    )
    url = f"/v1/test-stores/{stores['shop']}/manage"
    assert (await client.get(url, headers=as_user("adam"))).status_code == 200

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE memberships SET role = 'STAFF' WHERE user_id = "
                "(SELECT id FROM users WHERE firebase_uid = 'fb-adam')"
            )
        )
    demoted = await client.get(url, headers=as_user("adam"))
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM memberships"))
    removed = await client.get(url, headers=as_user("adam"))

    assert demoted.status_code == 403
    assert removed.status_code == 404


async def test_staff_is_403_on_owner_admin_routes(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    _, stores = await seed_org(
        engine, "acme", {"alice": "OWNER", "sam": "STAFF"}, {"shop": "ACTIVE"}
    )
    url = f"/v1/test-stores/{stores['shop']}/manage"

    assert (await client.get(url, headers=as_user("sam"))).status_code == 403
    assert (await client.get(url, headers=as_user("alice"))).status_code == 200


async def test_user_in_two_organisations_only_reaches_the_matching_store(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    _, a = await seed_org(engine, "orga", {"alice": "STAFF"}, {"shop": "ACTIVE"})
    _, b = await seed_org(engine, "orgb", {"alice": "OWNER"}, {"shop": "ACTIVE"})

    in_a = await client.get(
        f"/v1/test-stores/{a['shop']}/info", headers=as_user("alice")
    )
    in_b = await client.get(
        f"/v1/test-stores/{b['shop']}/info", headers=as_user("alice")
    )

    assert (in_a.json()["role"], in_b.json()["role"]) == ("STAFF", "OWNER")


@pytest.mark.parametrize("status", ["SUSPENDED", "PROVISIONING"])
async def test_non_active_store_reads_work_and_writes_are_403(
    client: AsyncClient, engine: AsyncEngine, status: str
) -> None:
    _, stores = await seed_org(engine, "acme", {"alice": "OWNER"}, {"shop": status})
    base = f"/v1/test-stores/{stores['shop']}"

    read = await client.get(f"{base}/info", headers=as_user("alice"))
    write = await client.post(f"{base}/change", headers=as_user("alice"))

    assert read.status_code == 200
    assert write.status_code == 403
    assert write.json() == {"success": False, "error": "Store is not active"}


async def test_active_store_allows_writes_and_archived_store_is_404(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    _, stores = await seed_org(
        engine, "acme", {"alice": "OWNER"}, {"live": "ACTIVE", "old": "ARCHIVED"}
    )

    live = await client.post(
        f"/v1/test-stores/{stores['live']}/change", headers=as_user("alice")
    )
    archived = await client.get(
        f"/v1/test-stores/{stores['old']}/info", headers=as_user("alice")
    )

    assert live.status_code == 200
    assert archived.status_code == 404


async def test_authentication_failures_come_before_authorisation(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    _, stores = await seed_org(engine, "acme", {"alice": "OWNER"}, {"shop": "ACTIVE"})
    url = f"/v1/test-stores/{stores['shop']}/info"

    no_session = await client.get(url)
    unverified = await client.get(
        url, headers=as_user("alice", **{"X-Test-Verified": "no"})
    )
    bad_key = await client.get(
        url, headers={**as_user("alice"), "X-Internal-Key": "wrong"}
    )

    assert [r.status_code for r in (no_session, unverified, bad_key)] == [401, 403, 401]
