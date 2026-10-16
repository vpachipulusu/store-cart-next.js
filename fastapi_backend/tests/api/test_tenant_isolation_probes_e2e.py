"""Tenant isolation suite, part 2 (KAN-58, KAN-195): read-only API probes on one shared world.

Every test here sends a request that must fail the same way as a request for an id that
does not exist, and proves nothing changed. Because nothing may change, the whole module
shares one world (one platform database, no provisioned stores) instead of paying for a
fresh one per test. An autouse fixture snapshots the platform rows an attacker could
touch and the recorded Stripe calls around every test, so a probe that *did* write fails
on the spot instead of poisoning the tests after it.

Runs only when ``TEST_DATABASE_URL`` points at a throwaway local server whose database
name ends in ``_test`` (see ``tests/isolation_world.py``).
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic import SecretStr

from app.api.deps import get_session_provider
from app.api.v1.org_billing import stripe_billing
from app.core.config import settings
from app.core.ids import new_id
from tests.fakes_billing import FakeStripe
from tests.isolation_world import (
    STORE_SLUGS,
    World,
    as_user,
    header_identity_app,
    make_client,
    open_world,
    same_failure,
)
from tests.pg_scaffold import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

RETURN_URL = "https://app.example.com/settings/billing"
IDEMPOTENCY = {"Idempotency-Key": "isolation-key-1"}
UNKNOWN_PAYMENT_METHOD = "pm_other"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world() -> AsyncIterator[World]:
    with pytest.MonkeyPatch.context() as patch:
        async with open_world(patch) as built:
            yield built


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def stripe() -> FakeStripe:
    return FakeStripe()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client(world: World, stripe: FakeStripe) -> AsyncIterator[AsyncClient]:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "BILLING_RETURN_URL_ORIGINS", "https://app.example.com")
        patch.setattr(settings, "STRIPE_PRICE_ID_PRO_MONTHLY", "price_probe_pro_m")
        patch.setattr(settings, "STRIPE_WEBHOOK_SECRET", SecretStr("whsec_probes"))
        app = header_identity_app(world)
        assert get_session_provider in app.dependency_overrides
        app.dependency_overrides[stripe_billing] = lambda: stripe
        async with make_client(app) as http:
            yield http


@pytest_asyncio.fixture(autouse=True, loop_scope="module")
async def nothing_changes(world: World, stripe: FakeStripe) -> AsyncIterator[None]:
    before = await world.snapshot()
    calls = len(stripe.calls)
    yield
    assert await world.snapshot() == before, "a probe changed platform data"
    assert len(stripe.calls) == calls, "a probe reached Stripe"


async def test_listing_returns_only_the_callers_organisation_and_its_stores(
    client: AsyncClient, world: World
) -> None:
    alice = (await client.get("/v1/organizations", headers=as_user("alice"))).json()
    bob = (await client.get("/v1/organizations", headers=as_user("bob"))).json()
    eve = (await client.get("/v1/organizations", headers=as_user("eve"))).json()

    assert [org["id"] for org in alice["data"]] == [world.a.org_id]
    assert [org["id"] for org in bob["data"]] == [world.b.org_id]
    assert eve["data"] == []
    listed = {store["id"] for store in alice["data"][0]["stores"]}
    assert listed == set(world.a.stores.values())
    assert not listed & set(world.b.stores.values())


@pytest.mark.parametrize("user", ["alice", "amy", "eve"])
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/v1/organizations/{org}", None),
        ("PATCH", "/v1/organizations/{org}", {"name": "Hijacked"}),
        ("GET", "/v1/organizations/{org}/stores", None),
        ("POST", "/v1/organizations/{org}/stores", {"name": "Evil", "slug": "evil"}),
    ],
)
async def test_other_organisation_routes_are_not_found_and_indistinguishable(
    client: AsyncClient,
    world: World,
    user: str,
    method: str,
    path: str,
    body: dict[str, str] | None,
) -> None:
    foreign = await client.request(
        method, path.format(org=world.b.org_id), json=body, headers=as_user(user)
    )
    missing = await client.request(
        method, path.format(org=new_id()), json=body, headers=as_user(user)
    )

    assert foreign.status_code == 404
    same_failure(foreign, missing)
    assert world.b.org_id not in foreign.text
    org_name = await world.platform_value(
        "SELECT name FROM organizations WHERE id = :i", i=world.b.org_id
    )
    store_count = await world.platform_value(
        "SELECT count(*) FROM stores WHERE organization_id = :i", i=world.b.org_id
    )
    assert (org_name, store_count) == ("Org b", len(STORE_SLUGS))


@pytest.mark.parametrize("user", ["alice", "amy", "eve"])
@pytest.mark.parametrize("slug", STORE_SLUGS)
@pytest.mark.parametrize(
    ("method", "body"), [("GET", None), ("PATCH", {"name": "Hijacked"})]
)
async def test_other_organisations_store_is_not_found_and_indistinguishable(
    client: AsyncClient,
    world: World,
    user: str,
    slug: str,
    method: str,
    body: dict[str, str] | None,
) -> None:
    store_id = world.b.stores[slug]

    foreign = await client.request(
        method, f"/v1/stores/{store_id}", json=body, headers=as_user(user)
    )
    missing = await client.request(
        method, f"/v1/stores/{new_id()}", json=body, headers=as_user(user)
    )

    assert foreign.status_code == 404
    same_failure(foreign, missing)
    assert store_id not in foreign.text
    name = await world.platform_value(
        "SELECT name FROM stores WHERE id = :i", i=store_id
    )
    assert name == f"b {slug}"


async def test_ids_of_the_wrong_kind_and_other_tenants_attackers_find_nothing(
    client: AsyncClient, world: World
) -> None:
    probes = [
        ("/v1/stores/{}", world.a.org_id, "alice"),
        ("/v1/organizations/{}", world.a.stores["north"], "alice"),
        ("/v1/stores/{}", world.a.stores["north"], "bob"),
        ("/v1/organizations/{}", world.a.org_id, "bob"),
        ("/v1/organizations/{}/stores", world.a.org_id, "bob"),
    ]

    for template, known_id, user in probes:
        response = await client.get(template.format(known_id), headers=as_user(user))
        missing = await client.get(template.format(new_id()), headers=as_user(user))
        assert response.status_code == 404, template
        same_failure(response, missing)


async def test_forged_ownership_fields_in_a_foreign_write_change_nothing(
    client: AsyncClient, world: World
) -> None:
    target = world.b.stores["south"]
    forged = {
        "name": "Hijacked",
        "slug": "hijacked",
        "organization_id": world.a.org_id,
        "status": "ACTIVE",
        "connection_string_encrypted": "v1.x.y",
    }

    response = await client.patch(
        f"/v1/stores/{target}", json=forged, headers=as_user("alice")
    )

    # Authorisation runs before the body is validated: a foreign store is a plain 404.
    assert response.status_code == 404
    row = await world.platform_value(
        "SELECT name || '|' || slug || '|' || organization_id || '|' || "
        "coalesce(connection_string_encrypted, '') FROM stores WHERE id = :i",
        i=target,
    )
    assert row == f"b south|b-south|{world.b.org_id}|"


@pytest.mark.parametrize("store_id", ["x" * 129, "%00", "' OR 1=1 --", "A" * 24, "*"])
async def test_malformed_and_guessed_store_ids_are_all_plain_not_found(
    client: AsyncClient, store_id: str
) -> None:
    reference = await client.get(f"/v1/stores/{new_id()}", headers=as_user("alice"))

    response = await client.get(f"/v1/stores/{store_id}", headers=as_user("alice"))

    assert response.status_code == 404
    same_failure(response, reference)


async def test_selected_store_claims_are_not_an_authorisation_boundary(
    client: AsyncClient, world: World
) -> None:
    own = world.a.stores["north"]
    target = world.b.stores["north"]
    claims = {
        "X-Store-Id": own,
        "X-Selected-Store": own,
        "X-Organization-Id": world.a.org_id,
        "Cookie": f"selected_store={own}; store_id={own}",
    }

    response = await client.get(
        f"/v1/stores/{target}?store_id={own}&organization_id={world.a.org_id}",
        headers={**as_user("alice"), **claims},
    )

    assert response.status_code == 404
    assert target not in response.text


async def test_member_without_write_role_is_forbidden_in_own_org_and_blind_elsewhere(
    client: AsyncClient, world: World
) -> None:
    own_read = await client.get(
        f"/v1/stores/{world.a.stores['north']}", headers=as_user("amy")
    )
    own_write = await client.patch(
        f"/v1/stores/{world.a.stores['north']}",
        json={"name": "x"},
        headers=as_user("amy"),
    )
    foreign_write = await client.patch(
        f"/v1/stores/{world.b.stores['north']}",
        json={"name": "x"},
        headers=as_user("amy"),
    )

    assert own_read.status_code == 200
    assert own_write.status_code == 403
    assert foreign_write.status_code == 404


async def test_cross_organisation_store_create_adds_nothing(
    client: AsyncClient, world: World
) -> None:
    response = await client.post(
        f"/v1/organizations/{world.b.org_id}/stores",
        json={"name": "Intruder", "slug": "intruder"},
        headers=as_user("alice"),
    )

    assert response.status_code == 404
    count = await world.platform_value(
        "SELECT count(*) FROM stores WHERE slug = 'intruder'"
    )
    assert count == 0


# --- KAN-195: platform admin routes, billing, slugs -----------------------------

ADMIN_ROUTES = [
    ("GET", "/v1/admin/users", None),
    ("GET", "/v1/admin/users/{user}", None),
    ("PATCH", "/v1/admin/users/{user}", {"display_name": "Hijacked"}),
    ("DELETE", "/v1/admin/users/{user}", None),
    (
        "PUT",
        "/v1/admin/users/{user}/admin",
        {"role": "admin", "permissions": ["users.read"]},
    ),
    ("DELETE", "/v1/admin/users/{user}/admin", None),
    ("POST", "/v1/admin/users/{user}/ban", {"reason": "nope"}),
    ("POST", "/v1/admin/users/{user}/unban", None),
    ("GET", "/v1/admin/audit-logs", None),
    ("GET", "/v1/admin/audit-logs?organization_id={org}", None),
]


@pytest.mark.parametrize("user", ["alice", "dana", "amy", "bob", "eve"])
@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES)
async def test_organisation_roles_open_no_platform_admin_route(
    client: AsyncClient,
    world: World,
    user: str,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    target = world.user_ids["bob"]
    url = path.format(user=target, org=world.b.org_id)

    response = await client.request(method, url, json=body, headers=as_user(user))

    assert response.status_code == 403
    assert response.json() == {"success": False, "error": "Forbidden"}


BILLING_ROUTES = [
    ("GET", "", None, {}),
    (
        "POST",
        "/checkout",
        {
            "plan": "pro",
            "interval": "monthly",
            "success_url": RETURN_URL,
            "cancel_url": RETURN_URL,
        },
        IDEMPOTENCY,
    ),
    ("POST", "/portal", {"return_url": RETURN_URL}, IDEMPOTENCY),
    ("POST", "/plan", {"plan": "pro", "interval": "monthly"}, IDEMPOTENCY),
    ("POST", "/cancel", None, IDEMPOTENCY),
    ("POST", "/resume", None, IDEMPOTENCY),
    ("GET", "/invoices", None, {}),
    ("GET", "/payment-methods", None, {}),
    ("DELETE", f"/payment-methods/{UNKNOWN_PAYMENT_METHOD}", None, IDEMPOTENCY),
    ("POST", f"/payment-methods/{UNKNOWN_PAYMENT_METHOD}/default", None, IDEMPOTENCY),
]


@pytest.mark.parametrize("user", ["alice", "dana", "amy", "eve"])
@pytest.mark.parametrize(("method", "suffix", "body", "extra"), BILLING_ROUTES)
async def test_other_organisations_billing_is_not_found_and_never_reaches_stripe(
    client: AsyncClient,
    world: World,
    user: str,
    method: str,
    suffix: str,
    body: dict[str, Any] | None,
    extra: dict[str, str],
) -> None:
    headers = {**as_user(user), **extra}
    base = "/v1/organizations/{}/billing" + suffix

    foreign = await client.request(
        method, base.format(world.b.org_id), json=body, headers=headers
    )
    missing = await client.request(
        method, base.format(new_id()), json=body, headers=headers
    )

    assert foreign.status_code == 404
    same_failure(foreign, missing)
    assert world.b.org_id not in foreign.text


@pytest.mark.parametrize("user", ["alice", "dana"])
@pytest.mark.parametrize("target", ["organization", "store"])
async def test_a_slug_change_sent_to_another_organisation_is_not_found_even_for_admins(
    client: AsyncClient, world: World, user: str, target: str
) -> None:
    # dana is only an ADMIN at home (slug changes are forbidden there), yet abroad she
    # must still get the plain 404, never the 403 that would confirm the target exists.
    paths = {
        "organization": "/v1/organizations/{}",
        "store": "/v1/stores/{}",
    }
    known = {"organization": world.b.org_id, "store": world.b.stores["north"]}
    body = {"slug": "stolen-slug"}

    foreign = await client.patch(
        paths[target].format(known[target]), json=body, headers=as_user(user)
    )
    missing = await client.patch(
        paths[target].format(new_id()), json=body, headers=as_user(user)
    )

    assert foreign.status_code == 404
    same_failure(foreign, missing)


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/v1/organizations/{org}", {"slug": "org-b"}),
        ("/v1/stores/{store}", {"slug": "b-south"}),
    ],
    ids=["organization-slug", "store-slug"],
)
async def test_a_taken_slug_answers_with_a_bare_conflict_and_nothing_about_its_owner(
    client: AsyncClient, world: World, path: str, body: dict[str, str]
) -> None:
    url = path.format(org=world.a.org_id, store=world.a.stores["north"])

    response = await client.patch(url, json=body, headers=as_user("alice"))

    assert response.status_code == 409
    assert response.json() == {"success": False, "error": "Slug is already taken"}


async def test_no_response_lists_another_organisations_slugs(
    client: AsyncClient, world: World
) -> None:
    foreign_slugs = ["org-b", *(f"b-{slug}" for slug in STORE_SLUGS)]
    paths = [
        "/v1/organizations",
        f"/v1/organizations/{world.a.org_id}",
        f"/v1/organizations/{world.a.org_id}/stores",
        f"/v1/stores/{world.a.stores['north']}",
    ]

    for path in paths:
        response = await client.get(path, headers=as_user("alice"))
        assert response.status_code == 200, path
        for slug in foreign_slugs:
            assert f'"{slug}"' not in response.text, (path, slug)
