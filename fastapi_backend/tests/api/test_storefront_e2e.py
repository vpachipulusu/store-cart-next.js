"""End to end: the public storefront lookup on a real Postgres (KAN-65).

Runs only when ``TEST_DATABASE_URL`` points at a throwaway local database whose name ends
in "_test" (same contract as ``test_organizations_e2e.py``). The route, service and SQL are
the production code; it proves non-ACTIVE stores are invisible and no internal column leaks.
"""

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api.deps import get_session_provider
from app.core.database import DefaultSessionProvider, build_engine
from app.core.ids import new_id
from app.main import create_app
from app.models.platform.store import StoreStatus

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND_ROOT = Path(__file__).resolve().parents[2]
KEY = "test-only-internal-service-key-not-for-deployment"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
SECRET_REF = "neon-project-SECRET-REF"
SECRET_CONNECTION = "v1:SECRET-CIPHERTEXT-MUST-NEVER-LEAK"
NOT_FOUND = {"success": False, "error": "Store not found"}

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
        await connection.execute(text("TRUNCATE users, organizations CASCADE"))
    yield built
    await built.dispose()


@pytest.fixture
async def client(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    app = create_app()
    provider = DefaultSessionProvider(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    app.dependency_overrides[get_session_provider] = lambda: provider
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-Internal-Key": KEY}
    ) as http:
        yield http


async def seed_store(
    engine: AsyncEngine, slug: str, name: str, status: StoreStatus
) -> tuple[str, str]:
    """A store in its own organisation with secrets filled in; returns (org id, store id)."""
    org_id, store_id = new_id(), new_id()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO organizations (id, name, slug, subscription_tier) "
                "VALUES (:id, :n, :s, 'free')"
            ),
            {"id": org_id, "n": f"Org {slug}", "s": f"org-{org_id}"},
        )
        await connection.execute(
            text(
                "INSERT INTO stores (id, organization_id, name, slug, status, "
                "schema_version, database_ref, connection_string_encrypted) "
                "VALUES (:id, :org, :name, :slug, :status, 7, :ref, :conn)"
            ),
            {
                "id": store_id,
                "org": org_id,
                "name": name,
                "slug": slug,
                "status": status.value,
                "ref": SECRET_REF,
                "conn": SECRET_CONNECTION,
            },
        )
    return org_id, store_id


async def test_active_store_returns_exactly_its_public_fields(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    org_id, store_id = await seed_store(engine, "acme", "Acme Shop", StoreStatus.ACTIVE)

    response = await client.get("/v1/storefront/acme")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {"name": "Acme Shop", "slug": "acme"},
    }
    for private in (org_id, store_id, SECRET_REF, SECRET_CONNECTION, "ACTIVE"):
        assert private not in response.text
    assert set(response.headers).isdisjoint({"set-cookie"})


@pytest.mark.parametrize(
    "status",
    [s for s in StoreStatus if s is not StoreStatus.ACTIVE],
)
async def test_non_active_store_is_a_404_identical_to_an_unknown_slug(
    client: AsyncClient, engine: AsyncEngine, status: StoreStatus
) -> None:
    await seed_store(engine, "hidden-shop", "Hidden Shop", status)

    hidden = await client.get("/v1/storefront/hidden-shop")
    unknown = await client.get("/v1/storefront/never-existed")

    assert hidden.status_code == unknown.status_code == 404
    assert hidden.json() == unknown.json() == NOT_FOUND
    assert hidden.headers.keys() == unknown.headers.keys()
    assert hidden.headers["cache-control"] == unknown.headers["cache-control"]
    assert "Hidden Shop" not in hidden.text


async def test_each_slug_returns_only_its_own_store(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    await seed_store(engine, "alpha-shop", "Alpha", StoreStatus.ACTIVE)
    await seed_store(engine, "beta-shop", "Beta", StoreStatus.ACTIVE)

    alpha = await client.get("/v1/storefront/alpha-shop")
    beta = await client.get("/v1/storefront/beta-shop")

    assert alpha.json()["data"] == {"name": "Alpha", "slug": "alpha-shop"}
    assert beta.json()["data"] == {"name": "Beta", "slug": "beta-shop"}
    assert "Beta" not in alpha.text
    assert "Alpha" not in beta.text


async def test_status_change_is_visible_after_the_cache_window(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    await seed_store(engine, "flip-shop", "Flip", StoreStatus.ACTIVE)
    assert (await client.get("/v1/storefront/flip-shop")).status_code == 200

    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE stores SET status = 'SUSPENDED' WHERE slug = 'flip-shop'")
        )

    assert (await client.get("/v1/storefront/flip-shop")).status_code == 404


async def test_etag_is_stable_across_requests_and_304s(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    await seed_store(engine, "etag-shop", "Etag", StoreStatus.ACTIVE)

    first = await client.get("/v1/storefront/etag-shop")
    second = await client.get(
        "/v1/storefront/etag-shop", headers={"If-None-Match": first.headers["etag"]}
    )

    assert second.status_code == 304
    assert second.headers["etag"] == first.headers["etag"]
