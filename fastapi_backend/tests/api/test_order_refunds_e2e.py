"""Merchant refunds through the real app, Connect webhook and store databases (KAN-80).

``POST /v1/stores/{id}/orders/{id}/refunds`` reserves the refund, asks Stripe (a fake here) to
refund the payment on the connected account, and settles it from Stripe's answer; a refund Stripe
still processes is settled by the signed ``refund.*`` Connect webhook. Restock is the merchant's
choice per refund (default off) and happens once. Runs only when ``TEST_DATABASE_URL`` points at
a throwaway local server (see ``tests/isolation_world.py``).
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

from app.api.v1.order_refunds import get_stripe_refunds_client
from app.core.config import settings
from app.core.ids import new_id
from app.core.stripe_billing import StripeError, StripeRejected
from app.core.stripe_refunds import RefundRequest, StripeRefund
from app.core.stripe_signature import compute_signature
from app.services.store_migrations import migrate_store
from app.services.store_orders import OrderLineInput, create_order, mark_checkout_paid
from app.services.store_sessions import open_store_session
from tests.api.products_support import (
    as_user,
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

ACCOUNT = "acct_northorg"
WEBHOOK_SECRET = "whsec_e2e_refunds_only_not_real"
T0 = 1_800_000_000
PRICE = 1000
ALICE = as_user("alice")
DANA = as_user("dana")  # ADMIN
AMY = as_user("amy")  # STAFF: reads only
BOB = as_user("bob")  # another organisation


class FakeStripeRefunds:
    """Stripe refunds: one refund per idempotency key; answers are scripted per test."""

    def __init__(self) -> None:
        self.requests: list[RefundRequest] = []
        self.status = "pending"
        self.error: StripeError | None = None
        self.by_refund: dict[str, StripeRefund] = {}

    async def create_refund(self, request: RefundRequest) -> StripeRefund:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if request.refund_id not in self.by_refund:
            self.by_refund[request.refund_id] = StripeRefund(
                id=f"re_{new_id()}", status=self.status
            )
        return self.by_refund[request.refund_id]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world() -> AsyncIterator[World]:
    with pytest.MonkeyPatch.context() as patch:
        async with open_world(patch) as built:
            for label, slug in (("a", "north"), ("b", "north")):
                store_id = built.tenant(label).stores[slug]
                await built.provision(store_id)
                await migrate_store(store_id, built.provider)
            async with built.platform.begin() as connection:
                await connection.execute(
                    text("UPDATE organizations SET subscription_tier = 'enterprise'")
                )
            yield built


@pytest.fixture
def stripe() -> FakeStripeRefunds:
    return FakeStripeRefunds()


@pytest_asyncio.fixture(loop_scope="module")
async def client(
    world: World, stripe: FakeStripeRefunds, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(
        settings, "STRIPE_CONNECT_WEBHOOK_SECRET", SecretStr(WEBHOOK_SECRET)
    )
    await set_account(world, ACCOUNT)
    app = header_identity_app(world)
    app.dependency_overrides[get_stripe_refunds_client] = lambda: stripe
    async with make_client(app) as http:
        yield http


def north(world: World) -> str:
    return world.tenant("a").stores["north"]


def refunds_url(world: World, order_id: str) -> str:
    return f"/v1/stores/{north(world)}/orders/{order_id}/refunds"


async def set_account(world: World, account: str | None) -> None:
    async with world.platform.begin() as connection:
        await connection.execute(
            text(
                "UPDATE organizations SET stripe_connect_account_id = :acct,"
                " connect_charges_enabled = true WHERE id = :org"
            ),
            {"acct": account, "org": world.tenant("a").org_id},
        )


async def paid_order(
    client: AsyncClient, world: World, *, quantity: int = 3, stock: int = 10
) -> tuple[str, str, str]:
    """A paid order on a fresh product: (order id, variant id, order item id)."""
    payload = simple_payload(
        status="active",
        variants=[variant_payload(unique(), price_minor=PRICE, stock=stock)],
    )
    product = await create_product(client, north(world), "alice", payload)
    variant_id = product["variants"][0]["id"]
    async with open_store_session(north(world), world.provider) as session:
        order = await create_order(
            session,
            currency="GBP",
            tax_rate_bps=2000,
            lines=[OrderLineInput(variant_id=variant_id, quantity=quantity)],
        )
        await session.commit()
    async with open_store_session(north(world), world.provider) as session:
        await mark_checkout_paid(
            session,
            order_id=order.id,
            session_id=f"cs_{order.id}",
            payment_intent_id=f"pi_{order.id}",
            amount_minor=order.total_minor,
            currency="GBP",
        )
        await session.commit()
    return order.id, variant_id, order.items[0].id


async def stock_of(world: World, variant_id: str) -> int:
    value = await world.store_value(
        north(world), f"SELECT stock FROM variants WHERE id = '{variant_id}'"
    )
    return int(value)


async def status_of(world: World, order_id: str) -> str:
    return str(
        await world.store_value(
            north(world), f"SELECT status FROM orders WHERE id = '{order_id}'"
        )
    )


async def refund_rows(world: World, order_id: str) -> list[tuple[Any, ...]]:
    async with open_store_session(north(world), world.provider) as session:
        rows = await session.execute(
            text(
                "SELECT status, amount_minor, restock, stripe_refund_id "
                "FROM order_refunds WHERE order_id = :o ORDER BY created_at"
            ),
            {"o": order_id},
        )
        return [tuple(row) for row in rows]


async def refund(
    client: AsyncClient,
    world: World,
    order_id: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] = ALICE,
) -> Response:
    return await client.post(
        refunds_url(world, order_id),
        json=body if body is not None else {},
        headers=headers,
    )


def refund_event(
    world: World,
    sent: RefundRequest,
    stripe_refund: StripeRefund,
    *,
    status: str = "succeeded",
    event_type: str = "refund.updated",
    amount: int | None = None,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"evt_{new_id()}",
        "type": event_type,
        "created": T0,
        "livemode": False,
        "account": ACCOUNT,
        "data": {
            "object": {
                "id": stripe_refund.id,
                "object": "refund",
                "amount": sent.amount_minor if amount is None else amount,
                "currency": "gbp",
                "status": status,
                "payment_intent": sent.payment_intent_id,
                "metadata": metadata
                if metadata is not None
                else {
                    "store_id": north(world),
                    "order_id": sent.order_id,
                    "refund_id": sent.refund_id,
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


# --- requesting a refund ----------------------------------------------------------------


async def test_a_full_refund_asks_stripe_on_the_connected_account(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    order_id, variant_id, _ = await paid_order(client, world, quantity=3)
    total = 3 * PRICE + 3 * PRICE * 2000 // 10_000

    response = await refund(client, world, order_id)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    [sent] = stripe.requests
    assert sent.account_id == ACCOUNT
    assert sent.payment_intent_id == f"pi_{order_id}"
    assert sent.amount_minor == total
    assert sent.store_id == north(world)
    assert sent.order_id == order_id
    data = response.json()["data"]
    assert data["status"] == "paid"  # still pending at Stripe
    assert data["refunded_minor"] == 0
    [item_refund] = data["refunds"]
    assert item_refund["status"] == "pending"
    assert item_refund["amount_minor"] == total
    assert item_refund["restock"] is False
    assert await stock_of(world, variant_id) == 7


async def test_an_immediately_successful_refund_refunds_the_order_without_restock(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    stripe.status = "succeeded"
    order_id, variant_id, _ = await paid_order(client, world, quantity=3)

    response = await refund(client, world, order_id)

    data = response.json()["data"]
    assert (data["status"], data["refunded_minor"]) == ("refunded", data["total_minor"])
    assert data["refunds"][0]["status"] == "succeeded"
    assert await stock_of(world, variant_id) == 7  # restock is off by default


async def test_restock_returns_the_stock_once_stripe_confirms(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    stripe.status = "succeeded"
    order_id, variant_id, _ = await paid_order(client, world, quantity=3)

    response = await refund(client, world, order_id, {"restock": True})

    assert response.status_code == 200, response.text
    assert await stock_of(world, variant_id) == 10
    assert response.json()["data"]["refunds"][0]["restock"] is True
    assert response.json()["data"]["refunds"][0]["restocked_at"] is not None


async def test_a_partial_refund_covers_the_chosen_lines_only(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    stripe.status = "succeeded"
    order_id, variant_id, item_id = await paid_order(client, world, quantity=3)

    response = await refund(
        client,
        world,
        order_id,
        {"items": [{"order_item_id": item_id, "quantity": 2}], "restock": True},
    )

    data = response.json()["data"]
    assert data["status"] == "paid"
    assert data["refunded_minor"] == 2 * PRICE + 2 * PRICE * 2000 // 10_000
    assert await stock_of(world, variant_id) == 9  # 7 + 2
    again = await refund(
        client, world, order_id, {"items": [{"order_item_id": item_id, "quantity": 2}]}
    )
    assert again.status_code == 409  # only 1 left


# --- the webhook settles a pending refund -----------------------------------------------


async def test_the_webhook_settles_a_pending_refund_and_restocks_once(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    order_id, variant_id, _ = await paid_order(client, world, quantity=3)
    await refund(client, world, order_id, {"restock": True})
    [sent] = stripe.requests
    created = stripe.by_refund[sent.refund_id]
    event = refund_event(world, sent, created)

    first = await deliver(client, event)
    same_event = await deliver(client, event)  # Stripe retries the delivery
    other_event = await deliver(client, refund_event(world, sent, created))

    assert (first.status_code, same_event.status_code, other_event.status_code) == (
        200,
        200,
        200,
    )
    assert await status_of(world, order_id) == "refunded"
    assert await stock_of(world, variant_id) == 10  # restocked once, not three times
    assert [r[0] for r in await refund_rows(world, order_id)] == ["succeeded"]


async def test_concurrent_deliveries_restock_once(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    order_id, variant_id, _ = await paid_order(client, world, quantity=3)
    await refund(client, world, order_id, {"restock": True})
    [sent] = stripe.requests
    created = stripe.by_refund[sent.refund_id]

    responses = await asyncio.gather(
        *(deliver(client, refund_event(world, sent, created)) for _ in range(5))
    )

    assert {r.status_code for r in responses} == {200}
    assert await stock_of(world, variant_id) == 10
    assert await status_of(world, order_id) == "refunded"


async def test_a_failed_refund_event_releases_the_refund_and_restocks_nothing(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    order_id, variant_id, _ = await paid_order(client, world, quantity=3)
    await refund(client, world, order_id, {"restock": True})
    [sent] = stripe.requests
    created = stripe.by_refund[sent.refund_id]

    await deliver(
        client,
        refund_event(world, sent, created, status="failed", event_type="refund.failed"),
    )

    assert await status_of(world, order_id) == "paid"
    assert await stock_of(world, variant_id) == 7
    assert [r[0] for r in await refund_rows(world, order_id)] == ["failed"]
    stripe.status = "succeeded"
    retry = await refund(client, world, order_id)  # the units are free again
    assert retry.status_code == 200, retry.text


async def test_an_event_that_disagrees_with_the_refund_changes_nothing(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    order_id, variant_id, _ = await paid_order(client, world, quantity=3)
    await refund(client, world, order_id, {"restock": True})
    [sent] = stripe.requests
    created = stripe.by_refund[sent.refund_id]

    wrong_amount = await deliver(client, refund_event(world, sent, created, amount=1))
    wrong_order = await deliver(
        client,
        refund_event(
            world,
            sent,
            created,
            metadata={
                "store_id": north(world),
                "order_id": "other",
                "refund_id": sent.refund_id,
            },
        ),
    )

    assert (wrong_amount.status_code, wrong_order.status_code) == (200, 200)
    assert await status_of(world, order_id) == "paid"
    assert await stock_of(world, variant_id) == 7
    assert [r[0] for r in await refund_rows(world, order_id)] == ["pending"]


async def test_a_refund_made_elsewhere_is_acknowledged_and_ignored(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    order_id, _, _ = await paid_order(client, world)
    sent = RefundRequest(ACCOUNT, f"pi_{order_id}", 100, north(world), order_id, "x")

    response = await deliver(
        client,
        refund_event(
            world,
            sent,
            StripeRefund("re_dashboard", "succeeded"),
            metadata={"store_id": north(world)},
        ),
    )

    assert response.status_code == 200
    assert await status_of(world, order_id) == "paid"


# --- Stripe failures --------------------------------------------------------------------


async def test_a_refusal_by_stripe_is_a_409_and_frees_the_order(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    order_id, _, _ = await paid_order(client, world)
    stripe.error = StripeRejected("no")

    response = await refund(client, world, order_id)

    assert response.status_code == 409
    assert [r[0] for r in await refund_rows(world, order_id)] == ["failed"]
    stripe.error = None
    stripe.status = "succeeded"
    assert (await refund(client, world, order_id)).status_code == 200


async def test_an_unknown_outcome_is_a_502_and_keeps_the_refund_pending(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    order_id, _, _ = await paid_order(client, world)
    stripe.error = StripeError("down")

    response = await refund(client, world, order_id)

    assert response.status_code == 502
    assert [r[0] for r in await refund_rows(world, order_id)] == ["pending"]
    stripe.error = None
    # It may have happened: a second request must not refund the same money again.
    assert (await refund(client, world, order_id)).status_code == 409
    assert len(stripe.requests) == 1


async def test_no_connected_account_is_a_409_and_reserves_nothing(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    order_id, _, _ = await paid_order(client, world)
    await set_account(world, None)
    try:
        response = await refund(client, world, order_id)
    finally:
        await set_account(world, ACCOUNT)

    assert response.status_code == 409
    assert await refund_rows(world, order_id) == []
    assert stripe.requests == []


# --- access and validation --------------------------------------------------------------


async def test_concurrent_identical_requests_refund_once(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    order_id, _, _ = await paid_order(client, world)

    responses = await asyncio.gather(
        *(refund(client, world, order_id) for _ in range(5))
    )

    assert sorted(r.status_code for r in responses) == [200, 409, 409, 409, 409]
    assert len(stripe.requests) == 1


async def test_an_unpaid_order_cannot_be_refunded(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    payload = simple_payload(status="active")
    product = await create_product(client, north(world), "alice", payload)
    async with open_store_session(north(world), world.provider) as session:
        order = await create_order(
            session,
            currency="GBP",
            tax_rate_bps=0,
            lines=[OrderLineInput(product["variants"][0]["id"], 1)],
        )
        await session.commit()

    response = await refund(client, world, order.id)

    assert response.status_code == 409
    assert stripe.requests == []


async def test_roles_and_tenancy(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    stripe.status = "succeeded"
    order_id, _, _ = await paid_order(client, world)

    staff = await refund(client, world, order_id, headers=AMY)
    outsider = await refund(client, world, order_id, headers=BOB)
    missing = await refund(client, world, "no_such_order")
    admin = await refund(client, world, order_id, headers=DANA)

    assert staff.status_code == 403
    assert outsider.status_code == 404
    assert missing.status_code == 404
    assert admin.status_code == 200, admin.text
    assert len(stripe.requests) == 1


async def test_another_stores_order_cannot_be_refunded_through_this_store(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    stripe.status = "succeeded"
    foreign_store = world.tenant("b").stores["north"]
    product = await create_product(
        client, foreign_store, "bob", simple_payload(status="active")
    )
    async with open_store_session(foreign_store, world.provider) as session:
        foreign = await create_order(
            session,
            currency="GBP",
            tax_rate_bps=0,
            lines=[OrderLineInput(product["variants"][0]["id"], 1)],
        )
        await mark_checkout_paid(
            session,
            order_id=foreign.id,
            session_id="cs_foreign",
            payment_intent_id="pi_foreign",
            amount_minor=foreign.total_minor,
            currency="GBP",
        )
        await session.commit()

    through_own_store = await refund(client, world, foreign.id)
    through_foreign_store = await client.post(
        f"/v1/stores/{foreign_store}/orders/{foreign.id}/refunds",
        json={},
        headers=ALICE,
    )

    assert through_own_store.status_code == 404
    assert through_foreign_store.status_code == 404  # alice is not a member there
    assert stripe.requests == []
    async with open_store_session(foreign_store, world.provider) as session:
        status = await session.scalar(
            text("SELECT status FROM orders WHERE id = :i"), {"i": foreign.id}
        )
    assert status == "paid"


@pytest.mark.parametrize(
    "body",
    [
        {"restock": "yes"},
        {"restock": 1},
        {"unknown": True},
        {"items": []},
        {"items": [{"order_item_id": "x", "quantity": 0}]},
        {"items": [{"order_item_id": "x", "quantity": "2"}]},
        {"items": [{"order_item_id": "x", "quantity": 1, "price": 1}]},
    ],
)
async def test_invalid_bodies_are_422(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds, body: dict[str, Any]
) -> None:
    order_id, _, _ = await paid_order(client, world)

    response = await refund(client, world, order_id, body)

    assert response.status_code == 422
    assert stripe.requests == []


async def test_a_line_of_another_order_is_a_422(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    order_id, _, _ = await paid_order(client, world)
    _, _, other_item = await paid_order(client, world)

    response = await refund(
        client,
        world,
        order_id,
        {"items": [{"order_item_id": other_item, "quantity": 1}]},
    )

    assert response.status_code == 422
    assert stripe.requests == []


async def test_an_event_without_the_payment_intent_changes_nothing(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    order_id, variant_id, _ = await paid_order(client, world, quantity=3)
    await refund(client, world, order_id, {"restock": True})
    [sent] = stripe.requests
    event = refund_event(world, sent, stripe.by_refund[sent.refund_id])
    del event["data"]["object"]["payment_intent"]

    response = await deliver(client, event)

    assert response.status_code == 200
    assert await status_of(world, order_id) == "paid"
    assert await stock_of(world, variant_id) == 7


async def test_a_late_failure_after_success_is_not_applied(
    client: AsyncClient, world: World, stripe: FakeStripeRefunds
) -> None:
    order_id, variant_id, _ = await paid_order(client, world, quantity=3)
    await refund(client, world, order_id, {"restock": True})
    [sent] = stripe.requests
    created = stripe.by_refund[sent.refund_id]
    await deliver(client, refund_event(world, sent, created))

    late = await deliver(
        client,
        refund_event(world, sent, created, status="failed", event_type="refund.failed"),
    )

    assert late.status_code == 200
    assert await status_of(world, order_id) == "refunded"
    assert await stock_of(world, variant_id) == 10
    assert [r[0] for r in await refund_rows(world, order_id)] == ["succeeded"]
