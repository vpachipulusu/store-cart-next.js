"""Checkout on the merchant's connected account against real databases (KAN-68).

``POST /v1/storefront/{slug}/checkout`` turns the shopper's cart into a pending order priced
only on the server, then asks Stripe (a fake here) for a Checkout Session as a direct charge
on the store organisation's connected account. The Connect webhook marks the order paid once,
however often or concurrently Stripe delivers. Runs only when ``TEST_DATABASE_URL`` points at a
throwaway local server (see ``tests/isolation_world.py``).
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy import text

from app.api.v1.checkout import get_stripe_checkout_client
from app.core.config import settings
from app.core.ids import new_id
from app.core.stripe_billing import StripeRejected
from app.core.stripe_checkout import CheckoutSessionRequest, StripeCheckoutSession
from app.core.stripe_signature import compute_signature
from app.services import store_checkout
from app.services.store_checkout import confirm_checkout_payment
from app.services.store_migrations import migrate_store
from app.services.store_orders import PaymentOutcome
from app.services.store_sessions import open_store_session
from tests.api.products_support import (
    create_product,
    simple_payload,
    unique,
    variant_payload,
)
from tests.isolation_world import World, header_identity_app, make_client, open_world
from tests.pg_scaffold import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

SLUG = "a-north"
ACCOUNT = "acct_northorg"
WEBHOOK_SECRET = "whsec_e2e_checkout_only_not_real"
SUCCESS = "https://a-north.example.com/checkout/success"
CANCEL = "https://a-north.example.com/cart"
T0 = 1_800_000_000


class FakeStripeCheckout:
    def __init__(self) -> None:
        self.requests: list[CheckoutSessionRequest] = []
        self.fail = False

    async def create_payment_session(
        self, request: CheckoutSessionRequest
    ) -> StripeCheckoutSession:
        self.requests.append(request)
        if self.fail:
            raise StripeRejected("Stripe request failed")
        session_id = f"cs_test_{new_id()}"
        return StripeCheckoutSession(
            id=session_id, url=f"https://checkout.stripe.com/c/pay/{session_id}"
        )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world() -> AsyncIterator[World]:
    with pytest.MonkeyPatch.context() as patch:
        async with open_world(patch) as built:
            for label, slug in (("a", "north"), ("a", "south"), ("b", "north")):
                store_id = built.tenant(label).stores[slug]
                await built.provision(store_id)
                await migrate_store(store_id, built.provider)
            async with built.platform.begin() as connection:
                await connection.execute(
                    text("UPDATE organizations SET subscription_tier = 'enterprise'")
                )
            yield built


@pytest.fixture
def stripe() -> FakeStripeCheckout:
    return FakeStripeCheckout()


@pytest_asyncio.fixture(loop_scope="module")
async def client(
    world: World, stripe: FakeStripeCheckout, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(
        settings, "BILLING_RETURN_URL_ORIGINS", "https://app.example.com"
    )
    monkeypatch.setattr(settings, "PLATFORM_ROOT_DOMAIN", "example.com")
    monkeypatch.setattr(
        settings, "STRIPE_CONNECT_WEBHOOK_SECRET", SecretStr(WEBHOOK_SECRET)
    )
    await set_connect(world, account=ACCOUNT, charges=True, fee_bps=0)
    app = header_identity_app(world)
    app.dependency_overrides[get_stripe_checkout_client] = lambda: stripe
    async with make_client(app) as http:
        yield http


def north(world: World) -> str:
    return world.tenant("a").stores["north"]


async def set_connect(
    world: World, *, account: str | None, charges: bool, fee_bps: int
) -> None:
    async with world.platform.begin() as connection:
        await connection.execute(
            text(
                "UPDATE organizations SET stripe_connect_account_id = :acct, "
                "connect_charges_enabled = :charges, platform_fee_bps = :fee "
                "WHERE id = :org"
            ),
            {
                "acct": account,
                "charges": charges,
                "fee": fee_bps,
                "org": world.tenant("a").org_id,
            },
        )


async def run_sql(world: World, sql: str, **params: Any) -> None:
    async with open_store_session(north(world), world.provider) as session:
        await session.execute(text(sql), params)
        await session.commit()


async def order_row(world: World, order_id: str) -> dict[str, Any]:
    async with open_store_session(north(world), world.provider) as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT status, currency, subtotal_minor, shipping_minor,"
                        " tax_minor, total_minor, prices_include_tax,"
                        " stripe_checkout_session_id, stripe_payment_intent_id, paid_at"
                        " FROM orders WHERE id = :id"
                    ),
                    {"id": order_id},
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def order_count(world: World) -> int:
    return int(await world.store_value(north(world), "SELECT count(*) FROM orders"))


async def cart_with(
    client: AsyncClient, world: World, *, price: int = 1000, quantity: int = 2
) -> str:
    payload = simple_payload(
        status="active",
        variants=[variant_payload(unique(), price_minor=price, stock=10)],
    )
    product = await create_product(client, north(world), "alice", payload)
    response = await client.post(
        f"/v1/storefront/{SLUG}/cart/items",
        json={"variant_id": product["variants"][0]["id"], "quantity": quantity},
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["data"]["cart_token"]
    return token


async def checkout(client: AsyncClient, token: str | None, **body: Any) -> Response:
    return await client.post(
        f"/v1/storefront/{SLUG}/checkout",
        json={"success_url": SUCCESS, "cancel_url": CANCEL, **body},
        headers={"X-Cart-Token": token} if token else {},
    )


def session_event(
    world: World,
    request: CheckoutSessionRequest,
    session_id: str,
    *,
    event_type: str = "checkout.session.completed",
    livemode: bool = False,
    payment_status: str = "paid",
    amount: int | None = None,
) -> dict[str, Any]:
    total = sum(li.unit_amount_minor * li.quantity for li in request.line_items)
    return {
        "id": f"evt_{new_id()}",
        "type": event_type,
        "created": T0,
        "livemode": livemode,
        "account": ACCOUNT,
        "data": {
            "object": {
                "id": session_id,
                "object": "checkout.session",
                "amount_total": total if amount is None else amount,
                "currency": request.currency,
                "payment_status": payment_status,
                "payment_intent": f"pi_{new_id()}",
                "client_reference_id": request.order_id,
                "metadata": {
                    "store_id": north(world),
                    "order_id": request.order_id,
                },
            }
        },
    }


async def deliver(client: AsyncClient, event: dict[str, Any]) -> Response:
    body = json.dumps(event).encode()
    stamp = int(time.time())
    signature = compute_signature(WEBHOOK_SECRET, stamp, body)
    return await client.post(
        "/webhooks/stripe-connect",
        content=body,
        headers={"Stripe-Signature": f"t={stamp},v1={signature}"},
    )


async def started(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> tuple[str, str, CheckoutSessionRequest]:
    """A started checkout: (order id, session id, the request Stripe received)."""
    token = await cart_with(client, world)
    response = await checkout(client, token)
    assert response.status_code == 200, response.text
    order_id: str = response.json()["data"]["order_id"]
    session_id: str = (await order_row(world, order_id))["stripe_checkout_session_id"]
    return order_id, session_id, stripe.requests[-1]


# --- starting a checkout ----------------------------------------------------------------


async def test_checkout_creates_a_server_priced_order_and_a_direct_charge(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    await run_sql(
        world,
        "UPDATE store_settings SET shipping_flat_rate_minor = 499,"
        " tax_rate_bps = 2000, prices_include_tax = false",
    )
    try:
        token = await cart_with(client, world, price=1000, quantity=2)

        response = await checkout(client, token)
    finally:
        await run_sql(
            world,
            "UPDATE store_settings SET shipping_flat_rate_minor = 0, tax_rate_bps = 0",
        )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    data = response.json()["data"]
    assert data["checkout_url"].startswith("https://checkout.stripe.com/")
    row = await order_row(world, data["order_id"])
    assert row["status"] == "pending"
    assert (
        row["subtotal_minor"],
        row["shipping_minor"],
        row["tax_minor"],
        row["total_minor"],
    ) == (2000, 499, 400, 2899)
    assert row["stripe_checkout_session_id"].startswith("cs_test_")
    request = stripe.requests[-1]
    assert request.account_id == ACCOUNT
    assert request.application_fee_minor is None
    assert request.store_id == north(world)
    assert request.order_id == data["order_id"]
    assert request.idempotency_key == f"sc-checkout-{north(world)}-{data['order_id']}"
    assert sum(li.unit_amount_minor * li.quantity for li in request.line_items) == 2899


async def test_client_totals_are_not_accepted(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    token = await cart_with(client, world)
    before = await order_count(world)

    response = await checkout(client, token, total_minor=1, amount=1)

    assert response.status_code == 422
    assert stripe.requests == []
    assert await order_count(world) == before


async def test_a_platform_fee_rate_adds_an_application_fee(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    await set_connect(world, account=ACCOUNT, charges=True, fee_bps=250)
    token = await cart_with(client, world, price=999, quantity=1)

    response = await checkout(client, token)

    assert response.status_code == 200, response.text
    assert stripe.requests[-1].application_fee_minor == 25  # 24.975 -> 25


@pytest.mark.parametrize(("account", "charges"), [(ACCOUNT, False), (None, False)])
async def test_checkout_is_refused_until_charges_are_enabled(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    account: str | None,
    charges: bool,
) -> None:
    token = await cart_with(client, world)
    await set_connect(world, account=account, charges=charges, fee_bps=0)
    before = await order_count(world)

    response = await checkout(client, token)

    assert response.status_code == 409
    assert response.json() == {
        "success": False,
        "error": "Payments are not enabled for this store",
    }
    assert stripe.requests == []
    assert await order_count(world) == before


async def test_an_empty_cart_cannot_check_out(
    client: AsyncClient, stripe: FakeStripeCheckout
) -> None:
    response = await checkout(client, None)

    assert response.status_code == 409
    assert stripe.requests == []


async def test_a_return_url_outside_the_store_is_refused(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    token = await cart_with(client, world)

    response = await checkout(client, token, success_url="https://evil.example/ok")

    assert response.status_code == 422
    assert stripe.requests == []


async def test_an_unknown_store_is_404(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/storefront/no-such-store/checkout",
        json={"success_url": SUCCESS, "cancel_url": CANCEL},
    )

    assert response.status_code == 404


async def test_a_stripe_failure_is_502_and_cancels_the_order(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    token = await cart_with(client, world)
    stripe.fail = True

    response = await checkout(client, token)

    assert response.status_code == 502
    assert response.json()["error"] == "Payment could not be started. Try again."
    order_id = stripe.requests[-1].order_id
    assert (await order_row(world, order_id))["status"] == "cancelled"


# --- confirmation from the Connect webhook ----------------------------------------------


async def test_a_completed_session_marks_the_order_paid(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, session_id, request = await started(client, world, stripe)
    event = session_event(world, request, session_id)

    response = await deliver(client, event)

    assert response.status_code == 200
    row = await order_row(world, order_id)
    assert row["status"] == "paid"
    assert row["paid_at"] is not None
    assert row["stripe_payment_intent_id"] == event["data"]["object"]["payment_intent"]


async def test_duplicate_and_concurrent_deliveries_confirm_once(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, session_id, request = await started(client, world, stripe)
    event = session_event(world, request, session_id)
    # The same event redelivered, plus distinct events for the same session, all at once.
    others = [
        session_event(
            world,
            request,
            session_id,
            event_type="checkout.session.async_payment_succeeded",
        )
        for _ in range(2)
    ]

    responses = await asyncio.gather(
        *(deliver(client, e) for e in (event, event, event, *others))
    )
    first_paid = (await order_row(world, order_id))["paid_at"]
    again = await deliver(client, event)

    assert [r.status_code for r in responses] == [200] * 5
    assert again.status_code == 200
    row = await order_row(world, order_id)
    assert row["status"] == "paid"
    assert row["paid_at"] == first_paid


async def test_confirmation_rerun_in_the_store_database_changes_nothing(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    # Store side effects are at least once: the platform claim can roll back after the store
    # write committed, and Stripe's retry runs the handler again.
    order_id, session_id, request = await started(client, world, stripe)
    obj = session_event(world, request, session_id)["data"]["object"]

    async def confirm() -> None:
        async with open_store_session(north(world), world.provider) as session:
            await confirm_checkout_payment(session, obj)
            await session.commit()

    await confirm()
    first = await order_row(world, order_id)
    await asyncio.gather(confirm(), confirm())

    assert await order_row(world, order_id) == first
    assert first["status"] == "paid"


async def test_an_event_of_the_other_mode_is_ignored(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, session_id, request = await started(client, world, stripe)

    response = await deliver(
        client, session_event(world, request, session_id, livemode=True)
    )

    assert response.status_code == 200
    assert (await order_row(world, order_id))["status"] == "pending"


async def test_an_unpaid_completion_waits_for_the_async_success(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, session_id, request = await started(client, world, stripe)

    await deliver(
        client, session_event(world, request, session_id, payment_status="unpaid")
    )
    pending = (await order_row(world, order_id))["status"]
    await deliver(
        client,
        session_event(
            world,
            request,
            session_id,
            event_type="checkout.session.async_payment_succeeded",
        ),
    )

    assert pending == "pending"
    assert (await order_row(world, order_id))["status"] == "paid"


async def test_a_session_whose_amount_differs_does_not_pay_the_order(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, session_id, request = await started(client, world, stripe)

    response = await deliver(
        client, session_event(world, request, session_id, amount=1)
    )

    assert response.status_code == 200
    assert (await order_row(world, order_id))["status"] == "pending"


async def test_another_session_cannot_pay_an_order_linked_to_a_session(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, _session_id, request = await started(client, world, stripe)

    response = await deliver(
        client, session_event(world, request, f"cs_test_{new_id()}")
    )

    assert response.status_code == 200
    assert (await order_row(world, order_id))["status"] == "pending"


async def test_a_paid_session_for_a_cancelled_order_is_a_mismatch(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, session_id, request = await started(client, world, stripe)
    await run_sql(
        world, "UPDATE orders SET status = 'cancelled' WHERE id = :id", id=order_id
    )
    obj = session_event(world, request, session_id)["data"]["object"]

    async with open_store_session(north(world), world.provider) as session:
        outcome = await confirm_checkout_payment(session, obj)
        await session.commit()

    assert outcome is PaymentOutcome.MISMATCH
    row = await order_row(world, order_id)
    assert (row["status"], row["paid_at"]) == ("cancelled", None)


@pytest.fixture
def reported(monkeypatch: pytest.MonkeyPatch) -> list[BaseException]:
    seen: list[BaseException] = []
    monkeypatch.setattr(store_checkout, "report_exception", seen.append)
    return seen


async def test_a_session_in_another_currency_does_not_pay_the_order(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, session_id, request = await started(client, world, stripe)
    obj = session_event(world, request, session_id)["data"]["object"]

    async with open_store_session(north(world), world.provider) as session:
        outcome = await confirm_checkout_payment(session, {**obj, "currency": "eur"})
        await session.commit()

    assert outcome is PaymentOutcome.MISMATCH
    assert (await order_row(world, order_id))["status"] == "pending"


async def test_a_session_naming_a_sibling_store_finds_no_order_and_is_reported(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    reported: list[BaseException],
) -> None:
    order_id, session_id, request = await started(client, world, stripe)
    event = session_event(world, request, session_id)
    event["data"]["object"]["metadata"]["store_id"] = world.tenant("a").stores["south"]

    response = await deliver(client, event)

    assert response.status_code == 200
    assert [str(error) for error in reported] == ["not_found"]
    assert (await order_row(world, order_id))["status"] == "pending"


async def test_an_order_id_the_store_does_not_have_is_reported(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    reported: list[BaseException],
) -> None:
    _order_id, _session_id, request = await started(client, world, stripe)
    event = session_event(world, request, f"cs_test_{new_id()}")
    event["data"]["object"]["metadata"]["order_id"] = new_id()

    response = await deliver(client, event)

    assert response.status_code == 200
    assert [str(error) for error in reported] == ["not_found"]


async def test_the_webhook_can_pay_an_order_before_its_session_is_linked(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, session_id, request = await started(client, world, stripe)
    await run_sql(
        world,
        "UPDATE orders SET stripe_checkout_session_id = NULL WHERE id = :id",
        id=order_id,
    )

    response = await deliver(client, session_event(world, request, session_id))

    assert response.status_code == 200
    row = await order_row(world, order_id)
    assert (row["status"], row["stripe_checkout_session_id"]) == ("paid", session_id)
