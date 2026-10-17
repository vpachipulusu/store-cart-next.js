"""End to end: a merchant re-runs provisioning of a FAILED store on a real Postgres (KAN-242).

Same contract as ``test_admin_stores_e2e.py``: runs only when ``TEST_DATABASE_URL`` points
at a throwaway local database whose name ends in "_test", and rebuilds its schema with the
real Alembic migrations. Only Firebase (identity from an ``X-Test-Uid`` header), QStash
(a recording enqueuer) and the rate limiter backend (an in-memory fake) are replaced.
Fixtures are local to this module on purpose.
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
from app.api.deps import get_rate_limiter, get_session_provider
from app.core.database import DefaultSessionProvider, build_engine
from app.core.firebase import VerifiedIdentity
from app.core.ids import new_id
from app.core.rate_limit import RETRY_PROVISIONING_POLICY
from app.main import create_app
from app.services.admin_stores import (
    MAX_REPROVISION_ATTEMPTS,
)
from app.services.admin_stores import (
    RETRY_LIMIT_MESSAGE as RETRY_LIMIT_ERROR,
)
from tests.fakes import FakeRateLimiter

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


class Published:
    """Records every QStash publish; ``fail`` makes publishes raise like QStash down."""

    def __init__(self) -> None:
        self.steps: list[tuple[str, str, int]] = []
        self.fail = False

    async def enqueue(self, store_id: str, step: Any, *, attempt: int = 0) -> None:
        if self.fail:
            from app.services.store_provisioning_job import EnqueueFailed

            raise EnqueueFailed
        self.steps.append((store_id, step.value, attempt))


@pytest.fixture
async def client(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    published = Published()
    # The merchant route builds its service with the admin route's factory.
    monkeypatch.setattr(
        "app.api.v1.admin_stores.get_step_enqueuer", lambda _settings: published
    )
    app = create_app()
    provider = DefaultSessionProvider(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    limiter = FakeRateLimiter()
    app.dependency_overrides[get_session_provider] = lambda: provider
    app.dependency_overrides[get_rate_limiter] = lambda: limiter

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
        http.published = published  # type: ignore[attr-defined]
        http.limiter = limiter  # type: ignore[attr-defined]
        yield http


async def seed_user(
    engine: AsyncEngine, name: str, org_id: str | None = None, role: str = "OWNER"
) -> str:
    user_id = new_id()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (id, firebase_uid, email, email_verified) "
                "VALUES (:id, :uid, :email, true)"
            ),
            {"id": user_id, "uid": f"fb-{name}", "email": f"{name}@example.com"},
        )
        if org_id is not None:
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (:id, :org, :user, :role)"
                ),
                {"id": new_id(), "org": org_id, "user": user_id, "role": role},
            )
    return user_id


async def seed_store(
    engine: AsyncEngine, org_id: str, slug: str, status: str = "FAILED"
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
                "VALUES (:id, :org, :name, :slug, :status, 0, 'ref', 'secret')"
            ),
            {
                "id": store_id,
                "org": org_id,
                "name": slug.title(),
                "slug": slug,
                "status": status,
            },
        )
    return store_id


async def seed_world(engine: AsyncEngine, status: str = "FAILED") -> str:
    """Organisation orgA with an owner, an admin and a staff member, plus an outsider."""
    store_id = await seed_store(engine, "orgA", "alpha", status)
    await seed_user(engine, "owner", "orgA", "OWNER")
    await seed_user(engine, "admin", "orgA", "ADMIN")
    await seed_user(engine, "staff", "orgA", "STAFF")
    await seed_store(engine, "orgB", "beta")
    await seed_user(engine, "outsider", "orgB", "OWNER")
    return store_id


async def rows(engine: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with engine.connect() as connection:
        return list((await connection.execute(text(sql), params)).all())


async def fail_again(engine: AsyncEngine, store_id: str) -> None:
    """The provisioning job (not under test here) gives up on the store again."""
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE stores SET status = 'FAILED' WHERE id = :i"), {"i": store_id}
        )


def as_user(name: str) -> dict[str, str]:
    return {"X-Test-Uid": f"fb-{name}", "User-Agent": "e2e-agent"}


def retry_path(store_id: str) -> str:
    return f"/v1/stores/{store_id}/retry-provisioning"


def retry_buckets(client: AsyncClient) -> set[str]:
    return {
        identifier
        for identifier, policy in client.limiter.hits  # type: ignore[attr-defined]
        if policy == RETRY_PROVISIONING_POLICY
    }


@pytest.mark.parametrize("role", ["owner", "admin"])
async def test_owner_and_admin_retry_a_failed_store(client, engine, role):
    store_id = await seed_world(engine)

    result = await client.post(retry_path(store_id), headers=as_user(role))
    stored = await rows(
        engine,
        "SELECT status, database_ref, connection_string_encrypted FROM stores "
        "WHERE id = :i",
        i=store_id,
    )

    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json() == {
        "success": True,
        "data": {
            "store_id": store_id,
            "status": "PROVISIONING",
            "attempt": 1,
            "max_attempts": MAX_REPROVISION_ATTEMPTS,
        },
    }
    assert client.published.steps == [(store_id, "create_database", 1)]
    # The orphan database reference and connection string are kept for reuse.
    assert stored[0] == ("PROVISIONING", "ref", "secret")


async def test_the_audit_row_names_the_merchant_and_the_store(client, engine):
    store_id = await seed_world(engine)
    owner = await rows(engine, "SELECT id FROM users WHERE firebase_uid = 'fb-owner'")

    await client.post(retry_path(store_id), headers=as_user("owner"))
    audit = await rows(
        engine,
        "SELECT user_id, action, store_id, organization_id, resource, resource_id, "
        "metadata FROM audit_logs",
    )

    assert len(audit) == 1
    user_id, action, store, org, resource, resource_id, metadata = audit[0]
    assert (user_id, action) == (owner[0][0], "stores.retry_provisioning")
    assert (store, org, resource, resource_id) == (store_id, "orgA", "stores", store_id)
    assert metadata["actor_role"] == "OWNER"
    assert metadata["before"] == {"status": "FAILED"}
    assert metadata["after"] == {"status": "PROVISIONING"}
    assert metadata["details"]["attempt"] == 1


@pytest.mark.parametrize(("caller", "expected"), [("staff", 403), ("outsider", 404)])
async def test_staff_and_other_organisations_cannot_retry(
    client, engine, caller, expected
):
    store_id = await seed_world(engine)

    result = await client.post(retry_path(store_id), headers=as_user(caller))
    stored = await rows(engine, "SELECT status FROM stores WHERE id = :i", i=store_id)

    assert result.status_code == expected
    assert stored[0][0] == "FAILED"
    assert client.published.steps == []
    assert await rows(engine, "SELECT 1 FROM audit_logs") == []


async def test_outsider_and_unknown_store_read_identically(client, engine):
    store_id = await seed_world(engine)

    outsider = await client.post(retry_path(store_id), headers=as_user("outsider"))
    unknown = await client.post(retry_path(new_id()), headers=as_user("owner"))
    anonymous = await client.post(retry_path(store_id))

    assert unknown.status_code == 404
    assert (outsider.status_code, outsider.json()) == (404, unknown.json())
    assert anonymous.status_code == 401


async def test_an_archived_store_is_not_found(client, engine):
    store_id = await seed_world(engine, status="ARCHIVED")

    result = await client.post(retry_path(store_id), headers=as_user("owner"))

    assert result.status_code == 404


@pytest.mark.parametrize("status", ["ACTIVE", "PROVISIONING", "SUSPENDED"])
async def test_only_a_failed_store_can_be_retried(client, engine, status):
    store_id = await seed_world(engine, status=status)

    result = await client.post(retry_path(store_id), headers=as_user("owner"))
    stored = await rows(engine, "SELECT status FROM stores WHERE id = :i", i=store_id)

    assert result.status_code == 409
    assert stored[0][0] == status
    assert client.published.steps == []
    assert await rows(engine, "SELECT 1 FROM audit_logs") == []


async def test_concurrent_retries_queue_one_chain(client, engine):
    store_id = await seed_world(engine)

    results = await asyncio.gather(
        *(client.post(retry_path(store_id), headers=as_user("owner")) for _ in range(4))
    )

    assert sorted(r.status_code for r in results) == [200, 409, 409, 409]
    assert client.published.steps == [(store_id, "create_database", 1)]
    assert len(await rows(engine, "SELECT 1 FROM audit_logs")) == 1


async def test_merchant_retries_share_the_cap_and_attempt_numbers_with_admin_reruns(
    client, engine
):
    store_id = await seed_world(engine)
    ops_id = await seed_user(engine, "ops")
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO admin_users (id, user_id, role, permissions) "
                "VALUES (:id, :u, 'admin', CAST(:p AS jsonb))"
            ),
            {"id": new_id(), "u": ops_id, "p": json.dumps(["stores.reprovision"])},
        )
    admin_path = f"/v1/admin/stores/{store_id}/reprovision"
    attempts = []

    for caller in ("ops", "owner", "admin"):
        path = admin_path if caller == "ops" else retry_path(store_id)
        result = await client.post(path, headers=as_user(caller))
        attempts.append(result.json()["data"]["attempt"])
        await fail_again(engine, store_id)
    merchant_capped = await client.post(retry_path(store_id), headers=as_user("owner"))
    admin_capped = await client.post(admin_path, headers=as_user("ops"))

    assert attempts == [1, 2, 3]
    assert merchant_capped.status_code == 409
    assert merchant_capped.json()["error"] == RETRY_LIMIT_ERROR
    assert admin_capped.status_code == 409
    assert admin_capped.json()["error"] == RETRY_LIMIT_ERROR
    assert [step[2] for step in client.published.steps] == [1, 2, 3]


async def test_a_failed_enqueue_is_502_frees_the_slot_and_leaves_the_store_failed(
    client, engine
):
    store_id = await seed_world(engine)
    client.published.fail = True

    broken = await client.post(retry_path(store_id), headers=as_user("owner"))
    stored = await rows(engine, "SELECT status FROM stores WHERE id = :i", i=store_id)
    client.published.fail = False
    retried = await client.post(retry_path(store_id), headers=as_user("owner"))
    audit = await rows(engine, "SELECT action FROM audit_logs ORDER BY created_at")

    assert broken.status_code == 502
    assert broken.json()["error"] == "Provisioning could not be started"
    assert stored[0][0] == "FAILED"
    assert retried.status_code == 200
    assert retried.json()["data"]["attempt"] == 2  # the number is monotonic
    assert [a[0] for a in audit] == [
        "stores.retry_provisioning",
        "stores.retry_provisioning_failed",
        "stores.retry_provisioning",
    ]


async def test_errors_carry_no_store_data_or_internals(client, engine):
    store_id = await seed_world(engine, status="ACTIVE")

    refused = await client.post(retry_path(store_id), headers=as_user("owner"))
    forbidden = await client.post(retry_path(store_id), headers=as_user("staff"))

    for result in (refused, forbidden):
        assert "secret" not in result.text
        assert "Alpha" not in result.text
        assert store_id not in result.text


async def test_rate_limit_is_per_user_and_per_store_and_stops_the_retry(client, engine):
    store_id = await seed_world(engine, status="ACTIVE")  # 409s still count as hits
    limit = RETRY_PROVISIONING_POLICY.limit

    statuses = [
        (await client.post(retry_path(store_id), headers=as_user("owner"))).status_code
        for _ in range(limit + 1)
    ]
    other_user = await client.post(retry_path(store_id), headers=as_user("admin"))
    buckets = retry_buckets(client)

    assert statuses == [409] * limit + [429]
    assert other_user.status_code == 429  # the store bucket is spent for everyone
    assert f"{RETRY_PROVISIONING_POLICY.scope}:store:{store_id}" in buckets
    assert any(
        b.startswith(f"{RETRY_PROVISIONING_POLICY.scope}:user:") for b in buckets
    )


async def test_a_denied_caller_cannot_spend_the_store_bucket(client, engine):
    store_id = await seed_world(engine, status="ACTIVE")

    for _ in range(RETRY_PROVISIONING_POLICY.limit + 2):
        await client.post(retry_path(store_id), headers=as_user("outsider"))
    spent_by_outsider = {b for b in retry_buckets(client) if b.endswith(store_id)}
    owner = await client.post(retry_path(store_id), headers=as_user("owner"))

    assert spent_by_outsider == set()  # the 404 came before any retry bucket was hit
    assert owner.status_code == 409  # not 429


async def test_a_failed_enqueue_does_not_overwrite_a_store_the_job_moved_on(
    client, engine
):
    store_id = await seed_world(engine)
    original = client.published.enqueue

    async def job_finishes_then_enqueue_reports_failure(
        sid: str, step: Any, *, attempt: int = 0
    ) -> None:
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE stores SET status = 'ACTIVE' WHERE id = :i"), {"i": sid}
            )
        client.published.fail = True
        await original(sid, step, attempt=attempt)

    client.published.enqueue = job_finishes_then_enqueue_reports_failure

    result = await client.post(retry_path(store_id), headers=as_user("owner"))
    stored = await rows(engine, "SELECT status FROM stores WHERE id = :i", i=store_id)
    audit = await rows(engine, "SELECT action FROM audit_logs")

    assert result.status_code == 502
    assert stored[0][0] == "ACTIVE"
    assert [a[0] for a in audit] == ["stores.retry_provisioning"]
