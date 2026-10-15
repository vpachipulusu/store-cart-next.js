"""End to end: GET /v1/me exposes the caller's own admin flag and role (KAN-204).

Same contract as ``test_admin_users_e2e.py``: runs only against a throwaway local
database whose name ends in "_test". Only the session identity is replaced (an
``X-Test-Uid`` header); the repository, service and route are production code.
"""

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Iterator
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
from tests.api.test_admin_users_e2e import _migrate

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
KEY = "test-only-internal-service-key-not-for-deployment"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    assert TEST_DATABASE_URL is not None
    target = make_url(TEST_DATABASE_URL)
    assert (target.database or "").endswith("_test")
    assert target.host in LOCAL_HOSTS
    _migrate(TEST_DATABASE_URL, "downgrade", "base")
    _migrate(TEST_DATABASE_URL, "upgrade", "head")
    yield TEST_DATABASE_URL


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    built = build_engine(database_url)
    async with built.begin() as connection:
        await connection.execute(text("TRUNCATE users CASCADE"))
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


async def seed(
    engine: AsyncEngine,
    name: str,
    role: str | None = None,
    permissions: Any = None,
) -> None:
    user_id = new_id()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (id, firebase_uid, email, email_verified) "
                "VALUES (:id, :uid, :email, true)"
            ),
            {"id": user_id, "uid": f"fb-{name}", "email": f"{name}@example.com"},
        )
        if role:
            await connection.execute(
                text(
                    "INSERT INTO admin_users (id, user_id, role, permissions) "
                    "VALUES (:id, :user_id, :role, CAST(:perms AS jsonb))"
                ),
                {
                    "id": new_id(),
                    "user_id": user_id,
                    "role": role,
                    "perms": json.dumps(permissions or []),
                },
            )


def as_user(name: str) -> dict[str, str]:
    return {"X-Test-Uid": f"fb-{name}"}


async def test_super_admin_sees_role(client, engine):
    await seed(engine, "root", "super_admin", ["*"])

    result = await client.get("/v1/me", headers=as_user("root"))

    assert result.status_code == 200
    assert result.json()["data"]["is_admin"] is True
    assert result.json()["data"]["admin_role"] == "super_admin"


async def test_admin_without_users_read_still_sees_flag(client, engine):
    await seed(engine, "ops", "admin", ["audit.read"])

    result = await client.get("/v1/me", headers=as_user("ops"))

    assert result.status_code == 200
    assert result.json()["data"]["is_admin"] is True
    assert result.json()["data"]["admin_role"] == "admin"


async def test_admin_with_empty_grant_still_sees_flag(client, engine):
    await seed(engine, "bare", "admin", [])

    result = await client.get("/v1/me", headers=as_user("bare"))

    assert result.json()["data"]["is_admin"] is True


async def test_non_admin_is_not_flagged(client, engine):
    await seed(engine, "shopper")

    result = await client.get("/v1/me", headers=as_user("shopper"))

    assert result.status_code == 200
    assert result.json()["data"]["is_admin"] is False
    assert result.json()["data"]["admin_role"] is None


async def test_caller_only_sees_their_own_flag(client, engine):
    await seed(engine, "root", "super_admin", ["*"])
    await seed(engine, "shopper")

    results = await asyncio.gather(
        client.get("/v1/me", headers=as_user("shopper")),
        client.get("/v1/me", headers=as_user("root")),
    )

    assert [r.json()["data"]["is_admin"] for r in results] == [False, True]


async def test_patch_response_carries_the_flag(client, engine):
    await seed(engine, "ops", "admin", ["audit.read"])

    result = await client.patch(
        "/v1/me", headers=as_user("ops"), json={"display_name": "Ops"}
    )

    assert result.status_code == 200
    assert result.json()["data"]["is_admin"] is True
    assert result.json()["data"]["admin_role"] == "admin"


async def test_unauthenticated_is_401(client):
    result = await client.get("/v1/me")

    assert result.status_code == 401
