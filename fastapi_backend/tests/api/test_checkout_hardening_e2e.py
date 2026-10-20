"""Checkout hardening against real databases (KAN-256).

One open order per cart (a double start gives one order and one session, a changed cart expires
the old session first), the session expiry on the order, ``checkout.session.expired`` on the
Connect webhook, the sweep backstop, and the merchant cancelling a pending order (the Stripe
session is expired before the order is cancelled). Reuses the world and helpers of
``test_checkout_e2e``; runs only when ``TEST_DATABASE_URL`` points at a throwaway local server.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.stripe_billing import StripeError
from app.core.stripe_checkout import (
    CheckoutLineItem,
    CheckoutSessionRequest,
    ExpireOutcome,
)
from app.services.store_checkout_expiry import sweep_expired_checkout_orders
from app.services.store_sessions import open_store_session
from tests.api.products_support import (
    as_user,
    create_product,
    simple_payload,
    unique,
    variant_payload,
)
from tests.api.test_checkout_e2e import (  # noqa: F401  (fixtures and helpers)
    ACCOUNT,
    CANCEL,
    SLUG,
    SUCCESS,
    FakeStripeCheckout,
    cart_with,
    checkout,
    client,
    deliver,
    north,
    run_sql,
    session_event,
    started,
    stripe,
    world,
)
from tests.isolation_world import World
from tests.pg_scaffold import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

ALICE = as_user("alice")
AMY = as_user("amy")
LIFETIME_FLOOR = timedelta(minutes=55)
LIFETIME_CEILING = timedelta(minutes=65)


async def order_state(world: World, order_id: str) -> dict[str, Any]:
    async with open_store_session(north(world), world.provider) as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT status, cart_id, stripe_checkout_session_id,"
                        " stripe_checkout_url, checkout_expires_at, paid_at"
                        " FROM orders WHERE id = :id"
                    ),
                    {"id": order_id},
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def pending_orders_of_cart(world: World, cart_id: str) -> int:
    async with open_store_session(north(world), world.provider) as session:
        count = await session.scalar(
            text(
                "SELECT count(*) FROM orders WHERE cart_id = :c AND status = 'pending'"
            ),
            {"c": cart_id},
        )
    return int(count or 0)


async def cart_and_variant(client: AsyncClient, world: World) -> tuple[str, str]:
    token = await cart_with(client, world, price=1500, quantity=1)
    cart = await client.get(
        f"/v1/storefront/{SLUG}/cart", headers={"X-Cart-Token": token}
    )
    assert cart.status_code == 200, cart.text
    return token, cart.json()["data"]["lines"][0]["variant_id"]


async def add_one(client: AsyncClient, token: str, variant_id: str) -> None:
    response = await client.post(
        f"/v1/storefront/{SLUG}/cart/items",
        json={"variant_id": variant_id, "quantity": 1},
        headers={"X-Cart-Token": token},
    )
    assert response.status_code == 200, response.text


def expired_event(
    world: World,
    order_id: str,
    session_id: str,
    event_type: str = "checkout.session.expired",
    **changes: Any,
) -> dict[str, Any]:
    request = CheckoutSessionRequest(
        account_id=ACCOUNT,
        currency="gbp",
        line_items=(CheckoutLineItem("x", 1, 1),),
        application_fee_minor=None,
        store_id=north(world),
        order_id=order_id,
        success_url=SUCCESS,
        cancel_url=CANCEL,
        idempotency_key="k",
    )
    event = session_event(
        world,
        request,
        session_id,
        event_type=event_type,
        payment_status="unpaid",
    )
    event["data"]["object"].update(changes)
    return event


def cancel_url(world: World, order_id: str) -> str:
    return f"/v1/stores/{north(world)}/orders/{order_id}/cancel"


def spy_on_expiry(
    monkeypatch: pytest.MonkeyPatch, world: World, stripe: FakeStripeCheckout
) -> list[str]:
    """The status of the order a session belongs to at the moment Stripe is asked to expire it."""
    seen: list[str] = []
    original = stripe.expire_session

    async def spy(account_id: str, session_id: str) -> ExpireOutcome:
        async with open_store_session(north(world), world.provider) as session:
            status = await session.scalar(
                text("SELECT status FROM orders WHERE stripe_checkout_session_id = :s"),
                {"s": session_id},
            )
        seen.append(str(status))
        return await original(account_id, session_id)

    monkeypatch.setattr(stripe, "expire_session", spy)
    return seen


def requests_for(stripe: FakeStripeCheckout, order_id: str) -> set[str]:
    return {r.idempotency_key for r in stripe.requests if r.order_id == order_id}


# --- one open order per cart ------------------------------------------------------------


async def test_a_repeated_start_for_an_unchanged_cart_returns_the_open_session(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    token = await cart_with(client, world)
    first = await checkout(client, token)
    before = len(stripe.requests)

    second = await checkout(client, token)

    assert second.status_code == 200, second.text
    assert second.json() == first.json()
    assert len(stripe.requests) == before
    assert stripe.expired == []


async def test_concurrent_double_clicks_give_one_order_and_one_session(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    token = await cart_with(client, world)

    responses = await asyncio.gather(*(checkout(client, token) for _ in range(4)))

    assert [r.status_code for r in responses] == [200] * 4
    bodies = {
        (r.json()["data"]["order_id"], r.json()["data"]["checkout_url"])
        for r in responses
    }
    assert len(bodies) == 1
    order_id = next(iter(bodies))[0]
    cart_id = (await order_state(world, order_id))["cart_id"]
    assert await pending_orders_of_cart(world, cart_id) == 1
    assert len(requests_for(stripe, order_id)) == 1


async def test_the_order_remembers_its_cart_session_page_and_expiry(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    token = await cart_with(client, world)

    response = await checkout(client, token)

    data = response.json()["data"]
    row = await order_state(world, data["order_id"])
    assert row["cart_id"] is not None
    assert row["stripe_checkout_url"] == data["checkout_url"]
    lifetime = row["checkout_expires_at"] - datetime.now(UTC)
    assert LIFETIME_FLOOR < lifetime < LIFETIME_CEILING
    assert stripe.requests[-1].expires_at == int(row["checkout_expires_at"].timestamp())


async def test_a_changed_cart_expires_the_old_session_then_cancels_the_old_order(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token, variant_id = await cart_and_variant(client, world)
    status_at_expiry = spy_on_expiry(monkeypatch, world, stripe)
    first = (await checkout(client, token)).json()["data"]
    old_session = (await order_state(world, first["order_id"]))[
        "stripe_checkout_session_id"
    ]
    await add_one(client, token, variant_id)

    second = await checkout(client, token)

    assert second.status_code == 200, second.text
    new = second.json()["data"]
    assert new["order_id"] != first["order_id"]
    assert new["checkout_url"] != first["checkout_url"]
    assert stripe.expired == [(ACCOUNT, old_session)]
    assert status_at_expiry == ["pending"]  # expired first, cancelled after
    assert (await order_state(world, first["order_id"]))["status"] == "cancelled"
    assert (await order_state(world, new["order_id"]))["status"] == "pending"
    cart_id = (await order_state(world, new["order_id"]))["cart_id"]
    assert await pending_orders_of_cart(world, cart_id) == 1


async def test_a_changed_cart_keeps_the_old_order_when_stripe_cannot_expire_it(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    token, variant_id = await cart_and_variant(client, world)
    first = (await checkout(client, token)).json()["data"]
    await add_one(client, token, variant_id)
    stripe.expire_error = StripeError("down")

    response = await checkout(client, token)

    assert response.status_code == 502
    assert (await order_state(world, first["order_id"]))["status"] == "pending"


async def test_a_changed_cart_is_refused_when_the_old_session_was_paid(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    token, variant_id = await cart_and_variant(client, world)
    first = (await checkout(client, token)).json()["data"]
    await add_one(client, token, variant_id)
    stripe.expire_outcome = ExpireOutcome.COMPLETE

    response = await checkout(client, token)

    assert response.status_code == 409
    assert (await order_state(world, first["order_id"]))["status"] == "pending"


async def test_an_open_order_past_its_expiry_is_replaced(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    token = await cart_with(client, world)
    first = (await checkout(client, token)).json()["data"]
    await run_sql(
        world,
        "UPDATE orders SET checkout_expires_at = now() - interval '1 minute'"
        " WHERE id = :id",
        id=first["order_id"],
    )

    second = (await checkout(client, token)).json()["data"]

    assert second["order_id"] != first["order_id"]
    assert (await order_state(world, first["order_id"]))["status"] == "cancelled"


async def test_the_unlinked_open_order_is_resumed_not_duplicated(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    # The first start made a session at Stripe but the order never learned about it.
    token = await cart_with(client, world)
    first = (await checkout(client, token)).json()["data"]
    await run_sql(
        world,
        "UPDATE orders SET stripe_checkout_session_id = NULL,"
        " stripe_checkout_url = NULL WHERE id = :id",
        id=first["order_id"],
    )

    second = (await checkout(client, token)).json()["data"]

    assert second == first
    row = await order_state(world, first["order_id"])
    assert row["stripe_checkout_url"] == first["checkout_url"]
    assert len(requests_for(stripe, first["order_id"])) == 1


# --- checkout.session.expired ------------------------------------------------------------


async def test_an_expired_session_cancels_its_pending_order(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, session_id, _request = await started(client, world, stripe)

    response = await deliver(client, expired_event(world, order_id, session_id))

    assert response.status_code == 200
    assert (await order_state(world, order_id))["status"] == "cancelled"


async def test_the_expired_event_is_idempotent(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, session_id, _request = await started(client, world, stripe)
    event = expired_event(world, order_id, session_id)
    other = expired_event(world, order_id, session_id)

    responses = await asyncio.gather(
        *(deliver(client, e) for e in (event, event, other))
    )
    again = await deliver(client, event)

    assert [r.status_code for r in responses] == [200] * 3
    assert again.status_code == 200
    assert (await order_state(world, order_id))["status"] == "cancelled"


async def test_the_expired_event_does_not_touch_a_paid_order(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, session_id, request = await started(client, world, stripe)
    await deliver(client, session_event(world, request, session_id))

    response = await deliver(client, expired_event(world, order_id, session_id))

    assert response.status_code == 200
    row = await order_state(world, order_id)
    assert row["status"] == "paid"
    assert row["paid_at"] is not None


async def test_the_expired_event_of_another_session_leaves_the_order_pending(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, _session_id, _request = await started(client, world, stripe)

    response = await deliver(
        client, expired_event(world, order_id, "cs_test_someone_else")
    )

    assert response.status_code == 200
    assert (await order_state(world, order_id))["status"] == "pending"


async def test_an_expired_event_without_a_session_id_is_acknowledged(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, session_id, _request = await started(client, world, stripe)
    event = expired_event(world, order_id, session_id, id=42)

    response = await deliver(client, event)

    assert response.status_code == 200
    assert (await order_state(world, order_id))["status"] == "pending"


FAILED = "checkout.session.async_payment_failed"


async def test_a_failed_async_payment_cancels_the_order_and_frees_the_cart(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    token = await cart_with(client, world)
    first = (await checkout(client, token)).json()["data"]
    session_id = (await order_state(world, first["order_id"]))[
        "stripe_checkout_session_id"
    ]

    response = await deliver(
        client, expired_event(world, first["order_id"], session_id, FAILED)
    )

    assert response.status_code == 200
    assert (await order_state(world, first["order_id"]))["status"] == "cancelled"
    again = await checkout(client, token)  # the cart is not blocked
    assert again.status_code == 200, again.text
    assert again.json()["data"]["order_id"] != first["order_id"]


async def test_the_failed_payment_event_is_idempotent_and_leaves_paid_orders_alone(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, session_id, request = await started(client, world, stripe)
    await deliver(client, session_event(world, request, session_id))
    event = expired_event(world, order_id, session_id, FAILED)

    responses = [await deliver(client, event), await deliver(client, event)]

    assert [r.status_code for r in responses] == [200, 200]
    assert (await order_state(world, order_id))["status"] == "paid"


async def test_a_failed_payment_event_for_an_unknown_session_is_acknowledged(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, _session_id, _request = await started(client, world, stripe)

    response = await deliver(
        client, expired_event(world, order_id, "cs_test_unknown", FAILED)
    )

    assert response.status_code == 200
    assert (await order_state(world, order_id))["status"] == "pending"


# --- the sweep backstop -------------------------------------------------------------------


async def sweep(world: World, stripe: FakeStripeCheckout) -> int:
    async with open_store_session(north(world), world.provider) as session:
        page = await sweep_expired_checkout_orders(session, stripe, ACCOUNT)
    return page.cancelled


async def age(world: World, order_id: str, minutes: int) -> None:
    await run_sql(
        world,
        "UPDATE orders SET checkout_expires_at = now() - make_interval(mins => :minutes)"
        " WHERE id = :id",
        id=order_id,
        minutes=minutes,
    )


async def test_the_sweep_cancels_only_pending_orders_long_past_their_expiry(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    stale, stale_session, _r1 = await started(client, world, stripe)
    grace, _s2, _r2 = await started(client, world, stripe)
    fresh, _s3, _r3 = await started(client, world, stripe)
    paid, session_id, request = await started(client, world, stripe)
    await deliver(client, session_event(world, request, session_id))
    for order_id, minutes in ((stale, 120), (grace, 1), (paid, 120)):
        await age(world, order_id, minutes)

    cancelled = await sweep(world, stripe)

    assert cancelled >= 1
    assert (ACCOUNT, stale_session) in stripe.expired  # verified at Stripe first
    assert (await order_state(world, stale))["status"] == "cancelled"
    assert (await order_state(world, grace))["status"] == "pending"
    assert (await order_state(world, fresh))["status"] == "pending"
    assert (await order_state(world, paid))["status"] == "paid"


async def test_the_sweep_leaves_an_order_whose_session_was_completed(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    # A delayed payment method: completed but not yet paid, no expired event will ever come.
    order_id, _session_id, _request = await started(client, world, stripe)
    await age(world, order_id, 120)
    stripe.expire_outcome = ExpireOutcome.COMPLETE

    await sweep(world, stripe)

    assert (await order_state(world, order_id))["status"] == "pending"


async def test_the_sweep_leaves_an_order_stripe_cannot_verify(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, _session_id, _request = await started(client, world, stripe)
    await age(world, order_id, 120)
    stripe.expire_error = StripeError("down")

    await sweep(world, stripe)

    assert (await order_state(world, order_id))["status"] == "pending"


async def test_the_sweep_cancels_an_unlinked_order(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, _session_id, _request = await started(client, world, stripe)
    await run_sql(
        world,
        "UPDATE orders SET stripe_checkout_session_id = NULL WHERE id = :id",
        id=order_id,
    )
    await age(world, order_id, 120)

    await sweep(world, stripe)

    assert (await order_state(world, order_id))["status"] == "cancelled"


async def test_the_sweep_pages_past_orders_it_left_pending(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    held, _s1, _r1 = await started(client, world, stripe)
    later, _s2, _r2 = await started(client, world, stripe)
    await age(world, held, 180)
    await age(world, later, 120)
    stripe.expire_outcome = ExpireOutcome.COMPLETE  # the oldest stays pending

    async with open_store_session(north(world), world.provider) as session:
        first = await sweep_expired_checkout_orders(session, stripe, ACCOUNT, batch=1)
        assert first.cursor is not None
        stripe.expire_outcome = ExpireOutcome.EXPIRED
        second = await sweep_expired_checkout_orders(
            session, stripe, ACCOUNT, batch=1, after=first.cursor
        )

    assert (first.examined, first.cancelled) == (1, 0)
    assert second.examined == 1
    assert (await order_state(world, held))["status"] == "pending"


async def test_starting_a_checkout_sweeps_stale_unlinked_orders_without_stripe(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    unlinked, _s1, _r1 = await started(client, world, stripe)
    linked, _s2, _r2 = await started(client, world, stripe)
    await run_sql(
        world,
        "UPDATE orders SET stripe_checkout_session_id = NULL WHERE id = :id",
        id=unlinked,
    )
    await age(world, unlinked, 180)
    await age(world, linked, 180)
    calls = len(stripe.expired)
    token = await cart_with(client, world)

    response = await checkout(client, token)

    assert response.status_code == 200
    assert (await order_state(world, unlinked))["status"] == "cancelled"
    assert (await order_state(world, linked))[
        "status"
    ] == "pending"  # the command's job
    assert len(stripe.expired) == calls


# --- the merchant cancels a pending order -------------------------------------------------


async def test_cancelling_expires_the_stripe_session_before_cancelling_the_order(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, session_id, _request = await started(client, world, stripe)
    status_at_expiry = spy_on_expiry(monkeypatch, world, stripe)

    response = await client.post(cancel_url(world, order_id), headers=ALICE)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "cancelled"
    assert response.headers["cache-control"] == "no-store"
    assert stripe.expired == [(ACCOUNT, session_id)]
    assert status_at_expiry == ["pending"]  # expired first, cancelled after
    assert (await order_state(world, order_id))["status"] == "cancelled"


async def test_cancelling_keeps_the_order_when_the_shopper_already_paid(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, _session_id, _request = await started(client, world, stripe)
    stripe.expire_outcome = ExpireOutcome.COMPLETE

    response = await client.post(cancel_url(world, order_id), headers=ALICE)

    assert response.status_code == 409
    assert response.json()["error"] == "The order's payment is being processed"
    assert (await order_state(world, order_id))["status"] == "pending"


async def test_cancelling_keeps_the_order_when_stripe_cannot_be_reached(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, _session_id, _request = await started(client, world, stripe)
    stripe.expire_error = StripeError("down")

    response = await client.post(cancel_url(world, order_id), headers=ALICE)

    assert response.status_code == 502
    assert response.json() == {
        "success": False,
        "error": "The payment page could not be closed. Try again.",
    }
    assert (await order_state(world, order_id))["status"] == "pending"


async def test_cancelling_without_a_connected_account_changes_nothing(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, _session_id, _request = await started(client, world, stripe)
    async with world.platform.begin() as connection:
        await connection.execute(
            text(
                "UPDATE organizations SET stripe_connect_account_id = NULL"
                " WHERE id = :org"
            ),
            {"org": world.tenant("a").org_id},
        )

    try:
        response = await client.post(cancel_url(world, order_id), headers=ALICE)
    finally:
        async with world.platform.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE organizations SET stripe_connect_account_id = :acct"
                    " WHERE id = :org"
                ),
                {"acct": ACCOUNT, "org": world.tenant("a").org_id},
            )

    assert response.status_code == 502
    assert stripe.expired == []
    assert (await order_state(world, order_id))["status"] == "pending"


async def test_a_paid_order_cannot_be_cancelled_here(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, session_id, request = await started(client, world, stripe)
    await deliver(client, session_event(world, request, session_id))

    response = await client.post(cancel_url(world, order_id), headers=ALICE)

    assert response.status_code == 409
    assert response.json()["error"] == "Only a pending order can be cancelled"
    assert stripe.expired == []
    assert (await order_state(world, order_id))["status"] == "paid"


async def test_cancelling_twice_the_second_is_a_conflict_without_a_stripe_call(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, _session_id, _request = await started(client, world, stripe)
    await client.post(cancel_url(world, order_id), headers=ALICE)
    calls = len(stripe.expired)

    again = await client.post(cancel_url(world, order_id), headers=ALICE)

    assert again.status_code == 409
    assert len(stripe.expired) == calls


async def test_an_unknown_order_is_404(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    response = await client.post(cancel_url(world, "nope"), headers=ALICE)

    assert response.status_code == 404
    assert stripe.expired == []


async def test_staff_cannot_cancel_an_order(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, _session_id, _request = await started(client, world, stripe)

    response = await client.post(cancel_url(world, order_id), headers=AMY)

    assert response.status_code == 403
    assert stripe.expired == []
    assert (await order_state(world, order_id))["status"] == "pending"


async def test_an_order_of_another_store_cannot_be_cancelled_through_this_one(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, _session_id, _request = await started(client, world, stripe)
    south = world.tenant("a").stores["south"]

    response = await client.post(
        f"/v1/stores/{south}/orders/{order_id}/cancel", headers=ALICE
    )

    assert response.status_code == 404
    assert (await order_state(world, order_id))["status"] == "pending"


async def test_replaying_an_unlinked_order_sends_stripe_the_same_request(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    # Two distinct variants: the lines come back from the database in id order, which is not
    # the order they were first sent in. The key's parameters must still match.
    first_product = await create_product(
        client,
        north(world),
        "alice",
        simple_payload(
            status="active",
            variants=[variant_payload(unique(), price_minor=1200, stock=10)],
        ),
    )
    second_product = await create_product(
        client,
        north(world),
        "alice",
        simple_payload(
            status="active",
            variants=[variant_payload(unique(), price_minor=800, stock=10)],
        ),
    )
    token: str | None = None
    for product in (second_product, first_product):  # added in the reverse of id order
        response = await client.post(
            f"/v1/storefront/{SLUG}/cart/items",
            json={"variant_id": product["variants"][0]["id"], "quantity": 1},
            headers={"X-Cart-Token": token} if token else {},
        )
        assert response.status_code == 200, response.text
        token = token or response.json()["data"]["cart_token"]
    first = (await checkout(client, token)).json()["data"]
    await run_sql(
        world,
        "UPDATE orders SET stripe_checkout_session_id = NULL,"
        " stripe_checkout_url = NULL WHERE id = :id",
        id=first["order_id"],
    )

    second = await checkout(client, token)

    assert second.status_code == 200, second.text
    assert second.json()["data"] == first
    sent = [r for r in stripe.requests if r.order_id == first["order_id"]]
    assert len(sent) == 2
    assert sent[0] == sent[1]
    assert (await order_state(world, first["order_id"]))["status"] == "pending"
