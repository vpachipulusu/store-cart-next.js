"""End to end: the organisation and store routes on a real Postgres (KAN-59).

Same contract as ``test_merchant_e2e.py``: runs only when ``TEST_DATABASE_URL`` points at
a throwaway local database whose name ends in "_test", and rebuilds its schema with the
real Alembic migrations. Only Firebase is replaced (the session identity comes from an
``X-Test-Uid`` header). Routes, membership checks, locking, slug rules, plan limits,
audit rows and the error envelope are the production code.
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
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
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


async def seed_user(engine: AsyncEngine, name: str) -> str:
    async with engine.begin() as connection:
        found = (
            await connection.execute(
                text("SELECT id FROM users WHERE firebase_uid = :uid"),
                {"uid": f"fb-{name}"},
            )
        ).scalar_one_or_none()
        if found:
            return str(found)
        user_id = new_id()
        await connection.execute(
            text(
                "INSERT INTO users (id, firebase_uid, email, email_verified) "
                "VALUES (:id, :uid, :email, true)"
            ),
            {"id": user_id, "uid": f"fb-{name}", "email": f"{name}@example.com"},
        )
        return user_id


async def seed_org(
    engine: AsyncEngine,
    name: str,
    members: dict[str, str],
    stores: dict[str, str] | None = None,
    tier: str = "free",
) -> tuple[str, dict[str, str]]:
    """An organisation, members ``{user: role}`` and stores ``{slug: status}``."""
    org_id = new_id()
    store_ids = {slug: new_id() for slug in (stores or {})}
    user_ids = {user: await seed_user(engine, user) for user in members}
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO organizations (id, name, slug, subscription_tier) "
                "VALUES (:id, :n, :s, :t)"
            ),
            {"id": org_id, "n": name.title(), "s": f"{name}-{org_id}", "t": tier},
        )
        for user, role in members.items():
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (:id, :org, :user, :role)"
                ),
                {"id": new_id(), "org": org_id, "user": user_ids[user], "role": role},
            )
        for slug, status in (stores or {}).items():
            await connection.execute(
                text(
                    "INSERT INTO stores (id, organization_id, name, slug, status) "
                    "VALUES (:id, :org, :name, :slug, :status)"
                ),
                {
                    "id": store_ids[slug],
                    "org": org_id,
                    "name": slug.title(),
                    "slug": slug,
                    "status": status,
                },
            )
    return org_id, store_ids


async def scalar(engine: AsyncEngine, sql: str, **params: Any) -> Any:
    async with engine.connect() as connection:
        return (await connection.execute(text(sql), params)).scalar_one()


def as_user(name: str) -> dict[str, str]:
    return {"X-Test-Uid": f"fb-{name}"}


def error_of(response: Response) -> str:
    body = response.json()
    assert body["success"] is False
    return str(body["error"])


async def post_org(client: AsyncClient, user: str, name: str, slug: str) -> Response:
    return await client.post(
        "/v1/organizations", json={"name": name, "slug": slug}, headers=as_user(user)
    )


async def post_store(
    client: AsyncClient, user: str, org_id: str, slug: str, name: str = "Shop"
) -> Response:
    return await client.post(
        f"/v1/organizations/{org_id}/stores",
        json={"name": name, "slug": slug},
        headers=as_user(user),
    )


# --- list ---------------------------------------------------------------------


async def test_list_returns_only_callers_organisations_with_role_and_stores(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    mine, _ = await seed_org(
        engine,
        "mine",
        {"ann": "OWNER", "bob": "STAFF"},
        {"shop-one": "ACTIVE", "shop-two": "PROVISIONING", "old-shop": "ARCHIVED"},
    )
    staffed, _ = await seed_org(
        engine, "staffed", {"bob": "ADMIN"}, {"bob-shop": "ACTIVE"}
    )
    other, _ = await seed_org(engine, "other", {"cat": "OWNER"}, {"cat-shop": "ACTIVE"})

    ann = await client.get("/v1/organizations", headers=as_user("ann"))
    bob = await client.get("/v1/organizations", headers=as_user("bob"))

    assert ann.status_code == 200
    assert ann.headers["cache-control"] == "no-store"
    ann_body = ann.json()
    assert [org["id"] for org in ann_body["data"]] == [mine]
    assert ann_body["data"][0]["role"] == "OWNER"
    assert sorted(s["slug"] for s in ann_body["data"][0]["stores"]) == [
        "shop-one",
        "shop-two",
    ]
    assert ann_body["total"] == 1
    roles = {org["id"]: org["role"] for org in bob.json()["data"]}
    assert roles == {mine: "STAFF", staffed: "ADMIN"}
    assert other not in roles
    assert "stripe" not in ann.text
    assert "subscription" not in ann.text


async def test_list_is_empty_for_user_without_memberships(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    await seed_user(engine, "dan")

    response = await client.get("/v1/organizations", headers=as_user("dan"))

    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=x"])
async def test_list_rejects_out_of_bounds_pagination(
    client: AsyncClient, engine: AsyncEngine, query: str
) -> None:
    await seed_user(engine, "ann")

    response = await client.get(f"/v1/organizations?{query}", headers=as_user("ann"))

    assert response.status_code == 422


async def test_list_paginates(client: AsyncClient, engine: AsyncEngine) -> None:
    for index in range(3):
        await seed_org(engine, f"org{index}", {"ann": "OWNER"})

    page = await client.get(
        "/v1/organizations?limit=2&offset=2", headers=as_user("ann")
    )

    body = page.json()
    assert len(body["data"]) == 1
    assert (body["total"], body["limit"], body["offset"]) == (3, 2, 2)


# --- auth ---------------------------------------------------------------------


async def test_routes_require_internal_key_and_session(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    org_id, store_ids = await seed_org(
        engine, "acme", {"ann": "OWNER"}, {"shop": "ACTIVE"}
    )
    store_id = store_ids["shop"]
    urls = [
        ("GET", "/v1/organizations"),
        ("POST", "/v1/organizations"),
        ("GET", f"/v1/organizations/{org_id}"),
        ("PATCH", f"/v1/organizations/{org_id}"),
        ("GET", f"/v1/organizations/{org_id}/stores"),
        ("POST", f"/v1/organizations/{org_id}/stores"),
        ("GET", f"/v1/stores/{store_id}"),
        ("PATCH", f"/v1/stores/{store_id}"),
    ]
    for method, url in urls:
        wrong_key = await client.request(
            method, url, headers={"X-Internal-Key": "wrong", **as_user("ann")}, json={}
        )
        no_session = await client.request(method, url, json={})
        assert wrong_key.status_code == 401, (method, url)
        assert no_session.status_code == 401, (method, url)


# --- create organisation ------------------------------------------------------


async def test_create_organisation_makes_caller_owner_and_audits(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    await seed_user(engine, "ann")

    response = await post_org(client, "ann", "  Acme Inc  ", "Acme-Inc")

    assert response.status_code == 201
    data = response.json()["data"]
    assert (data["name"], data["slug"], data["role"]) == (
        "Acme Inc",
        "acme-inc",
        "OWNER",
    )
    assert data["stores"] == []
    role = await scalar(
        engine,
        "SELECT m.role FROM memberships m JOIN users u ON u.id = m.user_id "
        "WHERE m.organization_id = :o AND u.firebase_uid = 'fb-ann'",
        o=data["id"],
    )
    assert role == "OWNER"
    audit = await scalar(
        engine,
        "SELECT count(*) FROM audit_logs WHERE action = 'org.create' "
        "AND resource_id = :o AND organization_id = :o",
        o=data["id"],
    )
    assert audit == 1


@pytest.mark.parametrize(
    "extra", [{"role": "OWNER"}, {"organization_id": "x"}, {"owner": "fb-mallory"}]
)
async def test_create_organisation_rejects_authorisation_fields_in_body(
    client: AsyncClient, engine: AsyncEngine, extra: dict[str, str]
) -> None:
    await seed_user(engine, "ann")

    response = await client.post(
        "/v1/organizations",
        json={"name": "Acme", "slug": "acme-co", **extra},
        headers=as_user("ann"),
    )

    assert response.status_code == 422
    assert await scalar(engine, "SELECT count(*) FROM organizations") == 0


@pytest.mark.parametrize("slug", ["www", "admin", "api", "app", "APP", "mail", "cdn"])
async def test_create_organisation_rejects_reserved_slug(
    client: AsyncClient, engine: AsyncEngine, slug: str
) -> None:
    await seed_user(engine, "ann")

    response = await post_org(client, "ann", "Acme", slug)

    assert response.status_code == 422
    assert error_of(response) == "Slug is reserved"


@pytest.mark.parametrize(
    "slug", ["ab", "-abc", "abc-", "a--b", "a b", "café", "a" * 64]
)
async def test_create_organisation_rejects_bad_slug_format(
    client: AsyncClient, engine: AsyncEngine, slug: str
) -> None:
    await seed_user(engine, "ann")

    response = await post_org(client, "ann", "Acme", slug)

    assert response.status_code == 422
    assert "lowercase letters" in error_of(response)


@pytest.mark.parametrize(
    "name", ["   ", "x" * 101, "bad\x00name", "rtl" + chr(0x202E) + "override"]
)
async def test_create_organisation_rejects_bad_name(
    client: AsyncClient, engine: AsyncEngine, name: str
) -> None:
    await seed_user(engine, "ann")

    response = await post_org(client, "ann", name, "good-slug")

    assert response.status_code == 422


async def test_create_organisation_slug_unique_case_insensitively(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    await seed_user(engine, "ann")
    await seed_user(engine, "bob")

    first = await post_org(client, "ann", "A", "acme-co")
    second = await post_org(client, "bob", "B", "ACME-co")

    assert first.status_code == 201
    assert second.status_code == 409
    assert error_of(second) == "Slug is already taken"


async def test_concurrent_creates_of_one_slug_yield_one_winner(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    users = ["u1", "u2", "u3", "u4", "u5"]
    for name in users:
        await seed_user(engine, name)

    results = await asyncio.gather(
        *(post_org(client, name, "Race", "race-slug") for name in users)
    )

    assert sorted(r.status_code for r in results) == [201, 409, 409, 409, 409]
    assert await scalar(engine, "SELECT count(*) FROM organizations") == 1
    assert await scalar(engine, "SELECT count(*) FROM memberships") == 1


async def test_user_cannot_own_unlimited_organisations(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    for index in range(10):
        await seed_org(engine, f"owned{index}", {"ann": "OWNER"})

    response = await post_org(client, "ann", "One more", "one-more")

    assert response.status_code == 409
    assert error_of(response) == "Organization limit reached"


# --- read and update organisation ---------------------------------------------


async def test_organisation_read_is_404_for_non_member_and_unknown(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    org_id, _ = await seed_org(engine, "acme", {"ann": "OWNER"})
    await seed_user(engine, "eve")

    foreign = await client.get(f"/v1/organizations/{org_id}", headers=as_user("eve"))
    unknown = await client.get("/v1/organizations/nope", headers=as_user("eve"))

    assert foreign.status_code == unknown.status_code == 404
    assert foreign.content == unknown.content


async def test_owner_can_rename_and_change_slug_and_changes_are_audited(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    org_id, _ = await seed_org(engine, "acme", {"ann": "OWNER"})

    response = await client.patch(
        f"/v1/organizations/{org_id}",
        json={"name": "New Name", "slug": "New-Slug"},
        headers=as_user("ann"),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["name"], data["slug"]) == ("New Name", "new-slug")
    audited = await scalar(
        engine,
        "SELECT count(*) FROM audit_logs WHERE action = 'org.update' "
        "AND resource_id = :o AND metadata->'before'->>'slug' = :old",
        o=org_id,
        old=f"acme-{org_id}",
    )
    assert audited == 1


async def test_admin_can_rename_but_not_change_slug(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    org_id, _ = await seed_org(engine, "acme", {"ann": "OWNER", "adam": "ADMIN"})

    rename = await client.patch(
        f"/v1/organizations/{org_id}", json={"name": "Renamed"}, headers=as_user("adam")
    )
    slug = await client.patch(
        f"/v1/organizations/{org_id}", json={"slug": "sneaky"}, headers=as_user("adam")
    )

    assert rename.status_code == 200
    assert slug.status_code == 403
    name = await scalar(
        engine, "SELECT name FROM organizations WHERE id = :o", o=org_id
    )
    assert name == "Renamed"


async def test_staff_cannot_update_and_non_member_gets_404(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    org_id, _ = await seed_org(engine, "acme", {"ann": "OWNER", "sam": "STAFF"})
    await seed_user(engine, "eve")

    staff = await client.patch(
        f"/v1/organizations/{org_id}", json={"name": "X"}, headers=as_user("sam")
    )
    outsider = await client.patch(
        f"/v1/organizations/{org_id}", json={"name": "X"}, headers=as_user("eve")
    )

    assert staff.status_code == 403
    assert outsider.status_code == 404
    assert await scalar(engine, "SELECT count(*) FROM audit_logs") == 0


async def test_update_rejects_empty_body_taken_and_reserved_slugs(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    org_id, _ = await seed_org(engine, "acme", {"ann": "OWNER"})
    other, _ = await seed_org(engine, "other", {"bob": "OWNER"})
    url = f"/v1/organizations/{org_id}"

    empty = await client.patch(url, json={}, headers=as_user("ann"))
    taken = await client.patch(
        url, json={"slug": f"OTHER-{other}"}, headers=as_user("ann")
    )
    reserved = await client.patch(url, json={"slug": "admin"}, headers=as_user("ann"))

    assert empty.status_code == 422
    assert taken.status_code == 409
    assert reserved.status_code == 422


# --- stores -------------------------------------------------------------------


async def test_admin_creates_store_in_provisioning_and_it_is_audited(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    org_id, _ = await seed_org(engine, "acme", {"adam": "ADMIN"})

    response = await post_store(client, "adam", org_id, "Main-Shop", "Main Shop")

    assert response.status_code == 201
    data = response.json()["data"]
    assert (data["slug"], data["status"], data["organization_id"]) == (
        "main-shop",
        "PROVISIONING",
        org_id,
    )
    audited = await scalar(
        engine,
        "SELECT count(*) FROM audit_logs WHERE action = 'store.create' "
        "AND resource_id = :s",
        s=data["id"],
    )
    assert audited == 1


async def test_staff_cannot_create_store_and_outsider_gets_404(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    org_id, _ = await seed_org(engine, "acme", {"sam": "STAFF"})
    await seed_user(engine, "eve")

    staff = await post_store(client, "sam", org_id, "shop-one")
    outsider = await post_store(client, "eve", org_id, "shop-one")

    assert staff.status_code == 403
    assert outsider.status_code == 404
    assert await scalar(engine, "SELECT count(*) FROM stores") == 0


async def test_store_slug_rules_and_global_case_insensitive_uniqueness(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    org_a, _ = await seed_org(engine, "acme", {"ann": "OWNER"})
    org_b, _ = await seed_org(engine, "beta", {"bob": "OWNER"})

    first = await post_store(client, "ann", org_a, "taken-slug")
    clash = await post_store(client, "bob", org_b, "TAKEN-slug")
    reserved = await post_store(client, "bob", org_b, "www")
    malformed = await post_store(client, "bob", org_b, "-x-")

    assert first.status_code == 201
    assert clash.status_code == 409
    assert (reserved.status_code, malformed.status_code) == (422, 422)


async def test_store_limit_follows_plan_and_counts_non_archived_only(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    free_org, _ = await seed_org(
        engine, "freeco", {"ann": "OWNER"}, {"free-one": "ACTIVE"}
    )
    pro_org, _ = await seed_org(
        engine,
        "proco",
        {"bob": "OWNER"},
        {"pro-one": "ACTIVE", "pro-two": "ACTIVE", "pro-old": "ARCHIVED"},
        tier="pro",
    )

    free = await post_store(client, "ann", free_org, "free-two")
    pro_ok = await post_store(client, "bob", pro_org, "pro-three")
    pro_over = await post_store(client, "bob", pro_org, "pro-four")

    assert free.status_code == 409
    assert error_of(free) == "Store limit reached for the current plan"
    assert pro_ok.status_code == 201
    assert pro_over.status_code == 409


async def test_concurrent_store_creates_cannot_exceed_plan_limit(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    org_id, _ = await seed_org(engine, "acme", {"ann": "OWNER"})

    results = await asyncio.gather(
        *(post_store(client, "ann", org_id, f"race-store-{i}") for i in range(5))
    )

    assert sorted(r.status_code for r in results) == [201, 409, 409, 409, 409]
    assert await scalar(engine, "SELECT count(*) FROM stores") == 1


async def test_concurrent_store_creates_of_one_slug_yield_one_winner(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    orgs = [
        (await seed_org(engine, f"co{i}", {f"owner{i}": "OWNER"}))[0] for i in range(4)
    ]

    results = await asyncio.gather(
        *(
            post_store(client, f"owner{i}", org, "contested")
            for i, org in enumerate(orgs)
        )
    )

    assert sorted(r.status_code for r in results) == [201, 409, 409, 409]


async def test_store_list_is_paginated_hides_archived_and_404s_outsiders(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    org_id, _ = await seed_org(
        engine,
        "acme",
        {"sam": "STAFF"},
        {"s-one": "ACTIVE", "s-two": "ACTIVE", "s-old": "ARCHIVED"},
    )
    await seed_user(engine, "eve")
    url = f"/v1/organizations/{org_id}/stores"

    page = await client.get(f"{url}?limit=1", headers=as_user("sam"))
    outsider = await client.get(url, headers=as_user("eve"))
    too_big = await client.get(f"{url}?limit=500", headers=as_user("sam"))

    body = page.json()
    assert (len(body["data"]), body["total"]) == (1, 2)
    assert outsider.status_code == 404
    assert too_big.status_code == 422


async def test_store_read_uses_merchant_authorisation(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    _, stores = await seed_org(
        engine, "acme", {"sam": "STAFF"}, {"shop": "PROVISIONING", "gone": "ARCHIVED"}
    )
    await seed_user(engine, "eve")

    staff = await client.get(f"/v1/stores/{stores['shop']}", headers=as_user("sam"))
    outsider = await client.get(f"/v1/stores/{stores['shop']}", headers=as_user("eve"))
    unknown = await client.get("/v1/stores/unknown", headers=as_user("eve"))
    archived = await client.get(f"/v1/stores/{stores['gone']}", headers=as_user("sam"))

    assert staff.status_code == 200
    assert staff.json()["data"]["slug"] == "shop"
    assert "database_ref" not in staff.text
    assert "schema_version" not in staff.text
    assert outsider.status_code == unknown.status_code == 404
    assert outsider.content == unknown.content
    assert archived.status_code == 404


async def test_store_update_role_and_status_rules(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    _, stores = await seed_org(
        engine,
        "acme",
        {"ann": "OWNER", "adam": "ADMIN", "sam": "STAFF"},
        {"live": "ACTIVE", "booting": "PROVISIONING"},
        tier="enterprise",
    )
    live = f"/v1/stores/{stores['live']}"

    staff = await client.patch(live, json={"name": "X"}, headers=as_user("sam"))
    booting = await client.patch(
        f"/v1/stores/{stores['booting']}", json={"name": "X"}, headers=as_user("ann")
    )
    admin_slug = await client.patch(
        live, json={"slug": "nope-nope"}, headers=as_user("adam")
    )
    admin_name = await client.patch(
        live, json={"name": "Admin Rename"}, headers=as_user("adam")
    )
    owner_slug = await client.patch(
        live, json={"slug": "Brand-New"}, headers=as_user("ann")
    )

    assert staff.status_code == 403
    assert booting.status_code == 403
    assert error_of(booting) == "Store is not active"
    assert admin_slug.status_code == 403
    assert admin_name.status_code == 200
    assert owner_slug.status_code == 200
    assert owner_slug.json()["data"]["slug"] == "brand-new"
    audited = await scalar(
        engine, "SELECT count(*) FROM audit_logs WHERE action = 'store.update'"
    )
    assert audited == 2


async def test_store_update_slug_conflicts_and_reserved(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    _, stores = await seed_org(
        engine,
        "acme",
        {"ann": "OWNER"},
        {"first": "ACTIVE", "second": "ACTIVE"},
        tier="enterprise",
    )
    url = f"/v1/stores/{stores['first']}"

    taken = await client.patch(url, json={"slug": "SECOND"}, headers=as_user("ann"))
    reserved = await client.patch(url, json={"slug": "api"}, headers=as_user("ann"))
    same = await client.patch(
        url, json={"slug": "first", "name": "First"}, headers=as_user("ann")
    )

    assert taken.status_code == 409
    assert reserved.status_code == 422
    assert same.status_code == 200


async def test_store_update_for_foreign_store_is_404(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    _, stores = await seed_org(engine, "acme", {"ann": "OWNER"}, {"live": "ACTIVE"})
    await seed_org(engine, "other", {"eve": "OWNER"})

    response = await client.patch(
        f"/v1/stores/{stores['live']}", json={"name": "Hijack"}, headers=as_user("eve")
    )

    assert response.status_code == 404
    name = await scalar(
        engine, "SELECT name FROM stores WHERE id = :s", s=stores["live"]
    )
    assert name == "Live"


# --- database ----------------------------------------------------------------


async def test_database_rejects_mixed_case_slugs(engine: AsyncEngine) -> None:
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, name, slug) "
                    "VALUES ('x', 'X', 'MixedCase')"
                )
            )


@pytest.mark.parametrize("name", ["a\ud800b", "ㅤ", "⠀ ⠀", "a"])
async def test_create_organisation_rejects_unencodable_and_invisible_names(
    client: AsyncClient, engine: AsyncEngine, name: str
) -> None:
    await seed_user(engine, "ann")

    response = await client.post(
        "/v1/organizations",
        content=json.dumps({"name": name, "slug": "good-slug"}),
        headers={**as_user("ann"), "Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert await scalar(engine, "SELECT count(*) FROM organizations") == 0


async def test_concurrent_creates_by_one_user_cannot_exceed_owned_cap(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    for index in range(8):
        await seed_org(engine, f"owned{index}", {"ann": "OWNER"})

    results = await asyncio.gather(
        *(post_org(client, "ann", "Race", f"cap-race-{i}") for i in range(4))
    )

    assert sorted(r.status_code for r in results) == [201, 201, 409, 409]


async def test_update_refreshes_updated_at(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    org_id, _ = await seed_org(engine, "acme", {"ann": "OWNER"})
    before = await scalar(
        engine, "SELECT updated_at FROM organizations WHERE id = :o", o=org_id
    )
    await asyncio.sleep(0.05)

    response = await client.patch(
        f"/v1/organizations/{org_id}", json={"name": "Later"}, headers=as_user("ann")
    )

    stored = await scalar(
        engine, "SELECT updated_at FROM organizations WHERE id = :o", o=org_id
    )
    assert stored > before
    assert response.json()["data"]["updated_at"].startswith(stored.isoformat()[:19])


async def test_non_member_write_does_not_wait_on_the_organisation_lock(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    org_id, _ = await seed_org(engine, "acme", {"ann": "OWNER"})
    await seed_user(engine, "eve")
    async with engine.begin() as holder:
        await holder.execute(
            text("SELECT id FROM organizations WHERE id = :o FOR UPDATE"), {"o": org_id}
        )

        response = await asyncio.wait_for(
            client.patch(
                f"/v1/organizations/{org_id}",
                json={"name": "X"},
                headers=as_user("eve"),
            ),
            timeout=5,
        )

    assert response.status_code == 404
