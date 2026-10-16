"""Tenant isolation suite, part 3 (KAN-195): roles, lost access and the real auth chain.

Each test changes the world (a rename, a removed membership, a ban), so each gets a fresh
one. Most tests read the session identity from an ``X-Test-Uid`` header; the last block
runs the production chain instead (``X-Session-Token`` through ``AuthService`` and
``get_session_identity``), with only the Firebase network calls replaced by
``tests.isolation_world.FakeFirebase``.

Runs only when ``TEST_DATABASE_URL`` points at a throwaway local server whose database
name ends in ``_test`` (see ``tests/isolation_world.py``).
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.api.deps import get_session_provider
from app.core.ids import new_id
from app.main import create_app
from tests.isolation_world import (
    FakeFirebase,
    World,
    as_user,
    header_identity_app,
    make_client,
    open_world,
    same_failure,
    session_for,
)
from tests.pg_scaffold import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)


@pytest.fixture
async def world(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[World]:
    async with open_world(monkeypatch) as built:
        yield built


@pytest.fixture
async def client(world: World) -> AsyncIterator[AsyncClient]:
    async with make_client(header_identity_app(world)) as http:
        yield http


@pytest.fixture
def firebase(monkeypatch: pytest.MonkeyPatch) -> FakeFirebase:
    fake = FakeFirebase()
    provider = fake.provider_class()
    monkeypatch.setattr("app.api.auth.FirebaseIdentityProvider", provider)
    monkeypatch.setattr("app.api.v1.admin_users.FirebaseIdentityProvider", provider)
    return fake


@pytest.fixture
async def chain_client(
    world: World, firebase: FakeFirebase
) -> AsyncIterator[AsyncClient]:
    """The real app and auth chain; only the session provider points at the test world."""
    app = create_app()
    app.dependency_overrides[get_session_provider] = lambda: world.provider
    async with make_client(app) as http:
        yield http


async def org_value(world: World, column: str, org_id: str) -> Any:
    return await world.platform_value(
        f"SELECT {column} FROM organizations WHERE id = :i", i=org_id
    )


# --- ADMIN and STAFF roles --------------------------------------------------------


async def test_admin_renames_but_only_the_owner_changes_a_slug(
    client: AsyncClient, world: World
) -> None:
    org = world.a.org_id
    store = world.a.stores["north"]

    rename = await client.patch(
        f"/v1/organizations/{org}", json={"name": "By Dana"}, headers=as_user("dana")
    )
    org_slug = await client.patch(
        f"/v1/organizations/{org}", json={"slug": "dana-slug"}, headers=as_user("dana")
    )
    store_slug = await client.patch(
        f"/v1/stores/{store}", json={"slug": "dana-store"}, headers=as_user("dana")
    )
    owner_slug = await client.patch(
        f"/v1/organizations/{org}",
        json={"slug": "alice-slug"},
        headers=as_user("alice"),
    )

    assert rename.status_code == 200
    assert (org_slug.status_code, store_slug.status_code) == (403, 403)
    assert owner_slug.status_code == 200
    assert await org_value(world, "slug", org) == "alice-slug"
    assert await org_value(world, "name", org) == "By Dana"
    store_slug_now = await world.platform_value(
        "SELECT slug FROM stores WHERE id = :i", i=store
    )
    assert store_slug_now == "a-north"


async def test_admin_creates_stores_and_staff_cannot(
    client: AsyncClient, world: World
) -> None:
    async with world.platform.begin() as connection:
        await connection.execute(
            text("UPDATE organizations SET subscription_tier = 'enterprise'")
        )
    url = f"/v1/organizations/{world.a.org_id}/stores"

    by_staff = await client.post(
        url, json={"name": "Staff Shop", "slug": "staff-shop"}, headers=as_user("amy")
    )
    by_admin = await client.post(
        url, json={"name": "Admin Shop", "slug": "admin-shop"}, headers=as_user("dana")
    )

    assert by_staff.status_code == 403
    assert by_admin.status_code == 201
    slugs = await world.platform_value(
        "SELECT string_agg(slug, ',' ORDER BY slug) FROM stores "
        "WHERE slug LIKE '%-shop'"
    )
    assert slugs == "admin-shop"


async def test_staff_cannot_create_a_store(client: AsyncClient, world: World) -> None:
    response = await client.post(
        f"/v1/organizations/{world.a.org_id}/stores",
        json={"name": "Staff Shop", "slug": "staff-shop"},
        headers=as_user("amy"),
    )

    assert response.status_code == 403
    assert response.json() == {"success": False, "error": "Forbidden"}


async def test_an_admin_of_one_organisation_is_a_stranger_in_the_other(
    client: AsyncClient, world: World
) -> None:
    probes = [
        ("dana", "/v1/stores/{}", world.b.stores["north"]),
        ("gus", "/v1/stores/{}", world.a.stores["north"]),
        ("dana", "/v1/organizations/{}", world.b.org_id),
        ("gus", "/v1/organizations/{}", world.a.org_id),
    ]

    for user, template, known in probes:
        theirs = await client.patch(
            template.format(known), json={"name": "x"}, headers=as_user(user)
        )
        nothing = await client.patch(
            template.format(new_id()), json={"name": "x"}, headers=as_user(user)
        )
        assert theirs.status_code == 404, template
        same_failure(theirs, nothing)


# --- Lost access ------------------------------------------------------------------


async def test_a_removed_membership_loses_access_at_once(
    client: AsyncClient, world: World
) -> None:
    store_id, org_id = world.a.stores["north"], world.a.org_id
    probes = [
        ("/v1/stores/{}", store_id),
        ("/v1/organizations/{}", org_id),
        ("/v1/organizations/{}/stores", org_id),
    ]
    for template, known in probes:
        before = await client.get(template.format(known), headers=as_user("amy"))
        assert before.status_code == 200, template

    await world.remove_membership("amy", "a")

    for template, known in probes:
        gone = await client.get(template.format(known), headers=as_user("amy"))
        missing = await client.get(template.format(new_id()), headers=as_user("amy"))
        assert gone.status_code == 404, template
        same_failure(gone, missing)
    listing = (await client.get("/v1/organizations", headers=as_user("amy"))).json()
    assert listing["data"] == []


async def test_removing_one_membership_keeps_the_other_organisation(
    client: AsyncClient, world: World
) -> None:
    await world.remove_membership("carol", "b")

    in_a = await client.get(
        f"/v1/stores/{world.a.stores['east']}", headers=as_user("carol")
    )
    in_b = await client.get(
        f"/v1/stores/{world.b.stores['east']}", headers=as_user("carol")
    )

    assert in_a.status_code == 200
    assert in_b.status_code == 404


async def test_a_banned_user_loses_access_and_an_unbanned_one_gets_it_back(
    chain_client: AsyncClient, world: World, firebase: FakeFirebase
) -> None:
    await world.grant_platform_admin("root", ["users.read", "users.update"])
    bob_id = world.user_ids["bob"]
    mine = f"/v1/organizations/{world.b.org_id}"
    before = await chain_client.get(mine, headers=session_for("bob"))
    assert before.status_code == 200

    ban = await chain_client.post(
        f"/v1/admin/users/{bob_id}/ban", headers=session_for("root")
    )

    assert ban.status_code == 200
    for path in (mine, "/v1/organizations", f"/v1/stores/{world.b.stores['north']}"):
        denied = await chain_client.get(path, headers=session_for("bob"))
        assert denied.status_code == 401, path
    unban = await chain_client.post(
        f"/v1/admin/users/{bob_id}/unban", headers=session_for("root")
    )
    assert unban.status_code == 200
    after = await chain_client.get(mine, headers=session_for("bob"))
    assert after.status_code == 200


# --- The real auth chain ------------------------------------------------------------


async def test_cross_organisation_read_through_the_real_session_chain(
    chain_client: AsyncClient, world: World, firebase: FakeFirebase
) -> None:
    own = await chain_client.get(
        f"/v1/organizations/{world.a.org_id}", headers=session_for("alice")
    )
    other = await chain_client.get(
        f"/v1/organizations/{world.b.org_id}", headers=session_for("alice")
    )
    missing = await chain_client.get(
        f"/v1/organizations/{new_id()}", headers=session_for("alice")
    )

    assert own.status_code == 200
    assert other.status_code == 404
    same_failure(other, missing)
    assert world.b.org_id not in other.text
    assert ("verify", "session-alice") in firebase.calls


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({}, 401),
        ({"X-Test-Uid": "fb-alice"}, 401),
        ({"X-Session-Token": "not-a-session"}, 401),
        ({"X-Session-Token": ""}, 401),
        ({"X-Session-Token": "session-nobody"}, 404),
    ],
    ids=[
        "no-credentials",
        "test-header-only",
        "garbage-token",
        "empty",
        "unknown-user",
    ],
)
async def test_the_real_chain_ignores_test_headers_and_rejects_bad_sessions(
    chain_client: AsyncClient, world: World, headers: dict[str, str], status: int
) -> None:
    response = await chain_client.get(
        f"/v1/organizations/{world.a.org_id}", headers=headers
    )

    assert response.status_code == status
    assert world.a.org_id not in response.text
