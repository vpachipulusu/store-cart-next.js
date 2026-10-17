"""Tenant isolation, roles and failure modes of the product routes (KAN-245, KAN-195 AC 3).

Two organisations, every store on its own real database. Every product route is probed
with another organisation's store id, with the caller's own store id and another store's
product ids, and with a sibling store of the caller's own organisation: each must answer
exactly like an id that does not exist, and the owner's data must be untouched.
Runs only when ``TEST_DATABASE_URL`` points at a throwaway local server.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text

from tests.api.products_support import (  # noqa: F401  (fixtures)
    add_category,
    as_user,
    assert_no_database_text,
    client,
    create_product,
    error_of,
    product_payload,
    products_url,
    simple_payload,
    store_count,
    store_of,
    unique,
    variant_payload,
    world,
)
from tests.isolation_world import World, internal_key, same_failure
from tests.pg_scaffold import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

Probe = Callable[[AsyncClient, str, dict[str, Any], dict[str, str]], Any]


def routes() -> list[
    tuple[str, str, str, Callable[[dict[str, Any]], dict[str, Any] | None]]
]:
    """(name, method, path suffix, body builder) for every product route."""
    return [
        ("list", "GET", "", lambda p: None),
        ("create", "POST", "", lambda p: product_payload()),
        ("read", "GET", "/{pid}", lambda p: None),
        ("update", "PATCH", "/{pid}", lambda p: {"title": "Hijacked"}),
        ("delete", "DELETE", "/{pid}", lambda p: None),
        (
            "add_variant",
            "POST",
            "/{pid}/variants",
            lambda p: variant_payload(unique(), options={"Size": "S"}),
        ),
        (
            "update_variant",
            "PATCH",
            "/{pid}/variants/{vid}",
            lambda p: {"price_minor": 1, "sku": "HIJACK"},
        ),
        ("delete_variant", "DELETE", "/{pid}/variants/{vid}", lambda p: None),
        (
            "add_image",
            "POST",
            "/{pid}/images",
            lambda p: {"storage_key": f"stores/{p['store']}/{unique()}.png"},
        ),
        ("delete_image", "DELETE", "/{pid}/images/{iid}", lambda p: None),
    ]


async def seed_victim(client: AsyncClient, world: World) -> dict[str, Any]:
    """A product in b.north (owned by bob) with an image, and the ids a prober would try."""
    store = store_of(world, "b", "north")
    product = await create_product(client, store, "bob")
    image = await client.post(
        products_url(store, f"/{product['id']}/images"),
        json={"storage_key": f"stores/{store}/{unique()}.png"},
        headers=as_user("bob"),
    )
    product = image.json()["data"]
    return {
        "store": store,
        "pid": product["id"],
        "vid": product["variants"][0]["id"],
        "iid": product["images"][0]["id"],
        "before": product,
    }


async def send(
    client: AsyncClient,
    store_id: str,
    ids: dict[str, str],
    route: tuple[str, str, str, Callable[[dict[str, Any]], dict[str, Any] | None]],
    user: str,
) -> Response:
    _, method, suffix, body = route
    return await client.request(
        method,
        products_url(store_id, suffix.format(**ids)),
        json=body({"store": store_id}),
        headers=as_user(user),
    )


@pytest.mark.parametrize("route", routes(), ids=[r[0] for r in routes()])
async def test_a_foreign_store_id_answers_like_a_missing_store(
    client: AsyncClient, world: World, route: Any
) -> None:
    victim = await seed_victim(client, world)
    ids = {k: victim[k] for k in ("pid", "vid", "iid")}
    missing_ids = {"pid": unique(), "vid": unique(), "iid": unique()}

    foreign = await send(client, victim["store"], ids, route, "alice")
    missing = await send(client, unique(), missing_ids, route, "alice")

    same_failure(foreign, missing)
    assert foreign.status_code == 404
    assert error_of(foreign) == "Store not found"


@pytest.mark.parametrize(
    "route",
    [r for r in routes() if "{pid}" in r[2]],
    ids=[r[0] for r in routes() if "{pid}" in r[2]],
)
async def test_another_stores_ids_under_the_callers_own_store_are_missing_ids(
    client: AsyncClient, world: World, route: Any
) -> None:
    victim = await seed_victim(client, world)
    ids = {k: victim[k] for k in ("pid", "vid", "iid")}
    own_store = store_of(world, "a", "north")
    missing_ids = {"pid": unique(), "vid": unique(), "iid": unique()}

    foreign_ids = await send(client, own_store, ids, route, "alice")
    missing = await send(client, own_store, missing_ids, route, "alice")

    same_failure(foreign_ids, missing)
    assert foreign_ids.status_code == 404


@pytest.mark.parametrize(
    "route",
    [r for r in routes() if "{pid}" in r[2]],
    ids=[r[0] for r in routes() if "{pid}" in r[2]],
)
async def test_a_sibling_store_of_the_same_organisation_does_not_see_the_product(
    client: AsyncClient, world: World, route: Any
) -> None:
    store = store_of(world, "a", "north")
    sibling = store_of(world, "a", "south")
    product = await create_product(client, store, "alice")
    ids = {
        "pid": product["id"],
        "vid": product["variants"][0]["id"],
        "iid": unique(),
    }
    missing_ids = {"pid": unique(), "vid": unique(), "iid": unique()}

    in_sibling = await send(client, sibling, ids, route, "alice")
    missing = await send(client, sibling, missing_ids, route, "alice")

    same_failure(in_sibling, missing)
    assert in_sibling.status_code == 404


async def test_probes_never_change_the_owners_data(
    client: AsyncClient, world: World
) -> None:
    victim = await seed_victim(client, world)
    ids = {k: victim[k] for k in ("pid", "vid", "iid")}
    stores = [
        victim["store"],
        store_of(world, "a", "north"),
        store_of(world, "a", "south"),
    ]
    tables = ("products", "variants", "product_images", "product_categories")

    async def counts() -> dict[tuple[str, str], int]:
        return {
            (st, t): await store_count(world, st, f"SELECT count(*) FROM {t}")
            for st in stores
            for t in tables
        }

    before = await counts()
    for route in routes():
        if route[0] == "create":  # a legitimate write in the caller's own store
            continue
        for st in stores:
            if route[0] == "list" and st != victim["store"]:
                continue  # listing the caller's own store is legitimate
            response = await send(client, st, ids, route, "alice")
            assert response.status_code == 404, (route[0], st)
    assert await counts() == before
    after = await client.get(
        products_url(victim["store"], f"/{victim['pid']}"), headers=as_user("bob")
    )

    assert after.json()["data"] == victim["before"]


async def test_rows_exist_only_in_the_database_of_the_store_that_made_them(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "north")
    product = await create_product(client, store, "alice")
    pid = product["id"]

    counts = {
        label_slug: await store_count(
            world,
            store_of(world, *label_slug),
            f"SELECT count(*) FROM products WHERE id = '{pid}'",
        )
        for label_slug in [
            ("a", "north"),
            ("a", "south"),
            ("b", "north"),
            ("b", "south"),
        ]
    }

    assert counts == {
        ("a", "north"): 1,
        ("a", "south"): 0,
        ("b", "north"): 0,
        ("b", "south"): 0,
    }


async def test_a_member_of_two_organisations_is_scoped_per_store(
    client: AsyncClient, world: World
) -> None:
    """carol is STAFF of A and OWNER of B: B rights never leak into A."""
    in_b = await client.post(
        products_url(store_of(world, "b", "north")),
        json=simple_payload(),
        headers=as_user("carol"),
    )
    in_a = await client.post(
        products_url(store_of(world, "a", "north")),
        json=simple_payload(),
        headers=as_user("carol"),
    )
    read_a = await client.get(
        products_url(store_of(world, "a", "north")), headers=as_user("carol")
    )

    assert (in_b.status_code, in_a.status_code, read_a.status_code) == (201, 403, 200)


# --- roles, status and authentication ------------------------------------------------


async def test_staff_can_read_but_not_change(client: AsyncClient, world: World) -> None:
    store = store_of(world, "a", "north")
    product = await create_product(client, store, "alice")
    ids = {"pid": product["id"], "vid": product["variants"][0]["id"], "iid": unique()}

    results = {
        name: (await send(client, store, ids, route, "amy")).status_code
        for name, route in ((r[0], r) for r in routes())
    }

    assert results["list"] == results["read"] == 200
    writes = {k: v for k, v in results.items() if k not in {"list", "read"}}
    assert set(writes.values()) == {403}


async def test_admin_can_change_products(client: AsyncClient, world: World) -> None:
    store = store_of(world, "a", "north")

    created = await client.post(
        products_url(store), json=simple_payload(), headers=as_user("dana")
    )

    assert created.status_code == 201


async def test_a_user_without_an_organisation_gets_not_found(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "north")

    read = await client.get(products_url(store), headers=as_user("eve"))
    write = await client.post(
        products_url(store), json=simple_payload(), headers=as_user("eve")
    )

    assert (read.status_code, write.status_code) == (404, 404)
    same_failure(read, await client.get(products_url(unique()), headers=as_user("eve")))


async def test_requests_need_the_internal_key_and_a_session(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "north")

    no_key = await client.get(
        products_url(store), headers={**as_user("alice"), "X-Internal-Key": "wrong"}
    )
    no_session = await client.get(products_url(store))

    assert no_key.status_code == 401
    assert no_session.status_code == 401
    assert internal_key() not in no_key.text


async def test_a_suspended_store_can_be_read_but_not_changed(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "b", "east")
    product = await create_product(client, store, "bob")
    await set_status(world, store, "SUSPENDED")
    try:
        read = await client.get(
            products_url(store, f"/{product['id']}"), headers=as_user("bob")
        )
        write = await client.patch(
            products_url(store, f"/{product['id']}"),
            json={"title": "x"},
            headers=as_user("bob"),
        )
        remove = await client.delete(
            products_url(store, f"/{product['id']}"), headers=as_user("bob")
        )
    finally:
        await set_status(world, store, "ACTIVE")

    assert (read.status_code, write.status_code, remove.status_code) == (200, 403, 403)
    assert error_of(write) == "Store is not active"


async def test_an_archived_store_is_gone(client: AsyncClient, world: World) -> None:
    store = store_of(world, "b", "east")
    await set_status(world, store, "ARCHIVED")
    try:
        response = await client.get(products_url(store), headers=as_user("bob"))
    finally:
        await set_status(world, store, "ACTIVE")

    assert response.status_code == 404
    assert error_of(response) == "Store not found"


async def test_a_store_without_a_database_answers_a_fixed_503(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "east")  # never provisioned: no connection string

    response = await client.get(products_url(store), headers=as_user("alice"))

    assert response.status_code == 503
    assert error_of(response) == "Store database is not available"
    assert store not in response.text
    assert_no_database_text(response)


async def set_status(world: World, store_id: str, status: str) -> None:
    async with world.platform.begin() as connection:
        await connection.execute(
            text("UPDATE stores SET status = :s WHERE id = :i"),
            {"s": status, "i": store_id},
        )


# --- image storage keys --------------------------------------------------------------


def bad_keys(own: str, sibling: str, foreign: str) -> list[tuple[str, str]]:
    name = unique()
    return [
        ("foreign store prefix", f"stores/{foreign}/{name}.png"),
        ("sibling store prefix", f"stores/{sibling}/{name}.png"),
        ("prefix of another store that starts like ours", f"stores/{own}x/{name}.png"),
        ("own id as a path prefix of a longer id", f"stores/{own[:-1]}/{name}.png"),
        ("no prefix", f"{name}.png"),
        ("wrong root", f"store/{own}/{name}.png"),
        ("leading slash", f"/stores/{own}/{name}.png"),
        ("dot-dot traversal", f"stores/{own}/../{foreign}/{name}.png"),
        ("traversal into foreign", f"stores/{own}/..%2F{foreign}/{name}.png"),
        ("nested path", f"stores/{own}/nested/{name}.png"),
        ("other extension", f"stores/{own}/{name}.gif"),
        ("svg", f"stores/{own}/{name}.svg"),
        ("no extension", f"stores/{own}/{name}"),
        ("upper-case extension", f"stores/{own}/{name}.PNG"),
        ("trailing newline", f"stores/{own}/{name}.png\n"),
        ("trailing space", f"stores/{own}/{name}.png "),
        ("NUL byte", f"stores/{own}/{name}\x00.png"),
        ("empty name", f"stores/{own}/.png"),
        ("query string", f"stores/{own}/{name}.png?x=1"),
        ("too long", f"stores/{own}/{'a' * 300}.png"),
        ("empty", ""),
    ]


async def test_an_image_key_outside_the_stores_own_prefix_is_rejected(
    client: AsyncClient, world: World
) -> None:
    own = store_of(world, "a", "north")
    product = await create_product(client, own, "alice")
    cases = bad_keys(own, store_of(world, "a", "south"), store_of(world, "b", "north"))
    outcomes: dict[str, int] = {}

    for label, key in cases:
        response = await client.post(
            products_url(own, f"/{product['id']}/images"),
            json={"storage_key": key},
            headers=as_user("alice"),
        )
        outcomes[label] = response.status_code
        assert_no_database_text(response)
        if label not in ("empty", "NUL byte"):  # may fail in the schema first
            assert error_of(response) == "Image key does not belong to this store"

    assert set(outcomes.values()) == {422}, outcomes
    assert (
        await store_count(
            world,
            own,
            f"SELECT count(*) FROM product_images WHERE product_id = '{product['id']}'",
        )
        == 0
    )


@pytest.mark.parametrize("extension", ["jpg", "png", "webp"])
async def test_an_image_key_of_the_stores_own_prefix_is_accepted(
    client: AsyncClient, world: World, extension: str
) -> None:
    own = store_of(world, "a", "north")
    product = await create_product(client, own, "alice")

    response = await client.post(
        products_url(own, f"/{product['id']}/images"),
        json={"storage_key": f"stores/{own}/{unique()}-x_Y.{extension}"},
        headers=as_user("alice"),
    )

    assert response.status_code == 201


async def test_a_foreign_key_cannot_be_attached_by_naming_the_other_store_in_the_path(
    client: AsyncClient, world: World
) -> None:
    """The prefix comes from the membership, not from the URL the caller typed."""
    foreign_store = store_of(world, "b", "north")
    own = store_of(world, "a", "north")
    product = await create_product(client, own, "alice")

    through_foreign_path = await client.post(
        products_url(foreign_store, f"/{product['id']}/images"),
        json={"storage_key": f"stores/{foreign_store}/{unique()}.png"},
        headers=as_user("alice"),
    )

    assert through_foreign_path.status_code == 404
    assert (
        await store_count(
            world,
            own,
            f"SELECT count(*) FROM product_images WHERE product_id = '{product['id']}'",
        )
        == 0
    )


async def test_categories_of_another_store_cannot_be_assigned(
    client: AsyncClient, world: World
) -> None:
    own = store_of(world, "a", "north")
    foreign_category = await add_category(world, store_of(world, "b", "north"))

    response = await client.post(
        products_url(own),
        json=simple_payload(category_ids=[foreign_category]),
        headers=as_user("alice"),
    )

    assert response.status_code == 422
    assert error_of(response) == "Unknown category"
