"""Transactional order emails end to end on real databases (KAN-81).

The Connect webhook pays an order (the real checkout and webhook routes, Stripe faked), which
records the shopper's address and two outbox rows and publishes them; the signed QStash route
sends each one (Resend faked) and settles its row. Fulfilment does the same for the shipped
notice. QStash is a recorder here. Runs only when ``TEST_DATABASE_URL`` points at a throwaway
local server (see ``tests/isolation_world.py``).
"""

import base64
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy import text

from app.api.deps import get_email_sender, get_order_email_enqueuer
from app.api.v1.checkout import get_stripe_checkout_client
from app.core.config import settings
from app.core.ids import new_id
from app.services.email import EmailDisabled
from app.services.order_email_job import FAILED_PATH, SEND_PATH, OrderEmailJob
from app.services.store_migrations import migrate_store
from app.services.store_sessions import open_store_session
from tests.api.test_checkout_e2e import (
    ACCOUNT,
    WEBHOOK_SECRET,
    FakeStripeCheckout,
    deliver,
    north,
    session_event,
    set_connect,
    started,
)
from tests.fakes_email import RecordingEnqueuer, RecordingSender
from tests.isolation_world import World, header_identity_app, make_client, open_world
from tests.pg_scaffold import TEST_DATABASE_URL
from tests.qstash_tokens import make_token

pytestmark = [
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

BASE = "https://api.example.test"
SIGNING_KEY = "current-signing-key-for-tests"
APP_URL = "https://app.example.com"
SHOPPER = "shopper@example.com"
OWNER_ADMIN = ["alice@x.test", "dana@x.test"]  # carol and amy are STAFF of A


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world() -> AsyncIterator[World]:
    with pytest.MonkeyPatch.context() as patch:
        async with open_world(patch) as built:
            for label in ("a", "b"):
                store_id = built.tenant(label).stores["north"]
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


@pytest.fixture
def enqueuer() -> RecordingEnqueuer:
    return RecordingEnqueuer()


@pytest.fixture
def sender() -> RecordingSender:
    return RecordingSender()


@pytest_asyncio.fixture(loop_scope="module")
async def client(
    world: World,
    stripe: FakeStripeCheckout,
    enqueuer: RecordingEnqueuer,
    sender: RecordingSender,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(
        settings, "BILLING_RETURN_URL_ORIGINS", "https://app.example.com"
    )
    monkeypatch.setattr(settings, "PLATFORM_ROOT_DOMAIN", "example.com")
    monkeypatch.setattr(
        settings, "STRIPE_CONNECT_WEBHOOK_SECRET", SecretStr(WEBHOOK_SECRET)
    )
    monkeypatch.setattr(settings, "PROVISIONING_BASE_URL", BASE)
    monkeypatch.setattr(settings, "QSTASH_CURRENT_SIGNING_KEY", SecretStr(SIGNING_KEY))
    monkeypatch.setattr(settings, "QSTASH_NEXT_SIGNING_KEY", None)
    monkeypatch.setattr(settings, "APP_PUBLIC_URL", APP_URL)
    await set_connect(world, account=ACCOUNT, charges=True, fee_bps=0)
    app = header_identity_app(world)
    app.dependency_overrides[get_stripe_checkout_client] = lambda: stripe
    app.dependency_overrides[get_order_email_enqueuer] = lambda: enqueuer
    app.dependency_overrides[get_email_sender] = lambda: sender
    async with make_client(app) as http:
        yield http


def paid_event(
    world: World, request: Any, session_id: str, email: str | None = SHOPPER, **kw: Any
) -> dict[str, Any]:
    event = session_event(world, request, session_id, **kw)
    if email is not None:
        event["data"]["object"]["customer_details"] = {"email": email, "name": "Sam"}
    return event


async def pay(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    email: str | None = SHOPPER,
) -> tuple[str, dict[str, Any]]:
    order_id, session_id, request = await started(client, world, stripe)
    event = paid_event(world, request, session_id, email)
    response = await deliver(client, event)
    assert response.status_code == 200, response.text
    return order_id, event


async def send(client: AsyncClient, job: OrderEmailJob) -> Response:
    body = job.payload().encode()
    token = make_token(body, f"{BASE}{SEND_PATH}", SIGNING_KEY)
    return await client.post(
        SEND_PATH, content=body, headers={"Upstash-Signature": token}
    )


async def exhausted(client: AsyncClient, job: OrderEmailJob) -> Response:
    body = json.dumps(
        {"sourceBody": base64.b64encode(job.payload().encode()).decode()}
    ).encode()
    token = make_token(body, f"{BASE}{FAILED_PATH}", SIGNING_KEY)
    return await client.post(
        FAILED_PATH, content=body, headers={"Upstash-Signature": token}
    )


async def email_rows(world: World, order_id: str) -> dict[str, tuple[str, int, bool]]:
    async with open_store_session(north(world), world.provider) as session:
        rows = await session.execute(
            text(
                "SELECT kind, status, attempts, sent_at IS NOT NULL FROM order_emails"
                " WHERE order_id = :o"
            ),
            {"o": order_id},
        )
        return {row[0]: (row[1], row[2], row[3]) for row in rows}


async def customer_email(world: World, order_id: str) -> str | None:
    async with open_store_session(north(world), world.provider) as session:
        value = (
            await session.execute(
                text("SELECT customer_email FROM orders WHERE id = :o"), {"o": order_id}
            )
        ).scalar_one()
    return value  # type: ignore[no-any-return]


def kinds_for(enqueuer: RecordingEnqueuer, order_id: str) -> list[str]:
    return sorted(job.kind.value for job in enqueuer.jobs if job.order_id == order_id)


def job(world: World, order_id: str, kind: str) -> OrderEmailJob:
    from app.services.order_email_templates import OrderEmailKind

    return OrderEmailJob(north(world), order_id, OrderEmailKind(kind))


async def fulfil(client: AsyncClient, world: World, order_id: str) -> Response:
    return await client.post(
        f"/v1/stores/{north(world)}/orders/{order_id}/fulfil",
        json={"tracking_number": "TRK-42", "carrier": "Royal Mail"},
        headers={"X-Test-Uid": "fb-alice"},
    )


# --- payment ----------------------------------------------------------------------------


async def test_payment_records_the_address_and_publishes_both_emails(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    enqueuer: RecordingEnqueuer,
) -> None:
    order_id, _ = await pay(client, world, stripe)

    assert await customer_email(world, order_id) == SHOPPER
    assert await email_rows(world, order_id) == {
        "order_confirmation": ("pending", 0, False),
        "new_order_alert": ("pending", 0, False),
    }
    assert kinds_for(enqueuer, order_id) == ["new_order_alert", "order_confirmation"]
    assert {job.store_id for job in enqueuer.jobs} == {north(world)}


async def test_the_send_route_delivers_each_email_once(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    sender: RecordingSender,
) -> None:
    order_id, _ = await pay(client, world, stripe)

    for kind in ("order_confirmation", "new_order_alert", "order_confirmation"):
        response = await send(client, job(world, order_id, kind))
        assert response.status_code == 200, response.text

    confirmation, alert, other = sender.sent
    assert confirmation.to == SHOPPER
    assert sorted([alert.to, other.to]) == OWNER_ADMIN  # ordered by user id
    assert "a north" in confirmation.subject
    assert order_id in confirmation.text
    assert f"{APP_URL}/dashboard/orders/{order_id}" in alert.html
    assert len({m.idempotency_key for m in sender.sent}) == 3
    rows = await email_rows(world, order_id)
    assert rows["order_confirmation"] == ("sent", 0, True)
    assert rows["new_order_alert"] == ("sent", 0, True)


async def test_a_redelivery_republishes_only_rows_still_pending(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    enqueuer: RecordingEnqueuer,
) -> None:
    order_id, session_id, request = await started(client, world, stripe)
    await deliver(client, paid_event(world, request, session_id))
    assert (
        await send(client, job(world, order_id, "order_confirmation"))
    ).status_code == 200
    enqueuer.jobs.clear()

    # A second Stripe event for the same session finds the order already paid.
    response = await deliver(
        client,
        paid_event(
            world,
            request,
            session_id,
            "other@example.com",
            event_type="checkout.session.async_payment_succeeded",
        ),
    )

    assert response.status_code == 200
    assert kinds_for(enqueuer, order_id) == ["new_order_alert"]
    assert await customer_email(world, order_id) == SHOPPER  # written once, when paid


async def test_a_publish_failure_answers_500_and_stripes_retry_publishes(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    enqueuer: RecordingEnqueuer,
) -> None:
    order_id, session_id, request = await started(client, world, stripe)
    event = paid_event(world, request, session_id)
    enqueuer.fail = True

    failed = await deliver(client, event)
    enqueuer.fail = False
    retried = await deliver(client, event)  # Stripe redelivers the same event

    assert failed.status_code == 500
    assert retried.status_code == 200
    assert kinds_for(enqueuer, order_id) == ["new_order_alert", "order_confirmation"]
    assert set((await email_rows(world, order_id)).values()) == {("pending", 0, False)}


async def test_without_a_shopper_address_the_confirmation_is_skipped(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    sender: RecordingSender,
) -> None:
    order_id, _ = await pay(client, world, stripe, email=None)

    response = await send(client, job(world, order_id, "order_confirmation"))

    assert response.status_code == 200
    assert sender.sent == []
    assert (await email_rows(world, order_id))["order_confirmation"] == (
        "skipped",
        0,
        False,
    )


async def test_members_who_turned_email_off_get_no_alert(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    sender: RecordingSender,
) -> None:
    settings_id = new_id()
    async with world.platform.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO user_settings (id, user_id, email_notifications)"
                " VALUES (:id, :u, false)"
            ),
            {"id": settings_id, "u": world.user_ids["dana"]},
        )
    try:
        order_id, _ = await pay(client, world, stripe)
        await send(client, job(world, order_id, "new_order_alert"))
    finally:
        async with world.platform.begin() as connection:
            await connection.execute(
                text("DELETE FROM user_settings WHERE id = :id"), {"id": settings_id}
            )

    assert [m.to for m in sender.sent] == ["alice@x.test"]


async def test_a_store_template_is_used_and_escaped(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    sender: RecordingSender,
) -> None:
    async with open_store_session(north(world), world.provider) as session:
        await session.execute(
            text(
                "INSERT INTO store_email_templates (kind, subject, body_text) VALUES"
                " ('order_confirmation', 'Thanks! $order_total',"
                " '<b>Order</b> $order_id\n\n$items')"
            )
        )
        await session.commit()
    try:
        order_id, _ = await pay(client, world, stripe)
        await send(client, job(world, order_id, "order_confirmation"))
    finally:
        async with open_store_session(north(world), world.provider) as session:
            await session.execute(text("DELETE FROM store_email_templates"))
            await session.commit()

    [message] = sender.sent
    assert message.subject == "Thanks! USD 20.00"  # the store currency
    assert f"&lt;b&gt;Order&lt;/b&gt; {order_id}" in message.html
    assert "<b>" not in message.html


async def test_a_store_template_with_an_unknown_placeholder_falls_back_to_the_default(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    sender: RecordingSender,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    async with open_store_session(north(world), world.provider) as session:
        await session.execute(
            text(
                "INSERT INTO store_email_templates (kind, subject, body_text) VALUES"
                " ('order_confirmation', 'Hi $bogus', 'Body $bogus')"
            )
        )
        await session.commit()
    try:
        order_id, _ = await pay(client, world, stripe)
        await send(client, job(world, order_id, "order_confirmation"))
    finally:
        async with open_store_session(north(world), world.provider) as session:
            await session.execute(text("DELETE FROM store_email_templates"))
            await session.commit()

    [message] = sender.sent
    assert message.subject == "Your order from a north"  # the platform default
    assert "$bogus" not in message.text
    assert "store email template unusable" in caplog.text


async def test_disabled_email_skips_and_a_transient_error_retries(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    sender: RecordingSender,
) -> None:
    order_id, _ = await pay(client, world, stripe)
    sender.errors[SHOPPER] = EmailDisabled()
    from app.services.email import EmailDeliveryFailed

    skipped = await send(client, job(world, order_id, "order_confirmation"))
    sender.errors["alice@x.test"] = EmailDeliveryFailed()
    retried = await send(client, job(world, order_id, "new_order_alert"))

    assert skipped.status_code == 200
    assert retried.status_code == 500
    rows = await email_rows(world, order_id)
    assert rows["order_confirmation"] == ("skipped", 0, False)
    assert rows["new_order_alert"] == ("pending", 1, False)


async def test_the_failure_callback_marks_the_row_failed(
    client: AsyncClient, world: World, stripe: FakeStripeCheckout
) -> None:
    order_id, _ = await pay(client, world, stripe)

    response = await exhausted(client, job(world, order_id, "new_order_alert"))

    assert response.status_code == 200
    assert (await email_rows(world, order_id))["new_order_alert"] == (
        "failed",
        0,
        False,
    )


async def test_a_job_naming_another_store_reaches_only_that_stores_database(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    sender: RecordingSender,
) -> None:
    from app.services.order_email_templates import OrderEmailKind

    order_id, _ = await pay(client, world, stripe)
    other_store = world.tenant("b").stores["north"]
    foreign = OrderEmailJob(other_store, order_id, OrderEmailKind.ORDER_CONFIRMATION)

    response = await send(client, foreign)
    failed = await exhausted(client, foreign)

    assert (response.status_code, failed.status_code) == (200, 200)
    assert sender.sent == []  # store B's database has no such order
    rows = await email_rows(world, order_id)
    assert rows["order_confirmation"] == ("pending", 0, False)  # A's row untouched


async def test_a_job_naming_an_unknown_store_ends_quietly(
    client: AsyncClient, sender: RecordingSender
) -> None:
    from app.services.order_email_templates import OrderEmailKind

    unknown = OrderEmailJob(new_id(), "order1", OrderEmailKind.ORDER_CONFIRMATION)

    response = await send(client, unknown)

    assert response.status_code == 200
    assert sender.sent == []


# --- fulfilment -------------------------------------------------------------------------


async def test_fulfilment_publishes_the_shipped_notice_once(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    enqueuer: RecordingEnqueuer,
    sender: RecordingSender,
) -> None:
    order_id, _ = await pay(client, world, stripe)

    first = await fulfil(client, world, order_id)
    second = await fulfil(client, world, order_id)
    sent = await send(client, job(world, order_id, "order_shipped"))

    assert first.status_code == 200, first.text
    assert second.status_code == 409
    assert [k for k in kinds_for(enqueuer, order_id) if k == "order_shipped"] == [
        "order_shipped"
    ]
    assert sent.status_code == 200
    [message] = sender.sent
    assert message.to == SHOPPER
    assert "TRK-42" in message.text and "Royal Mail" in message.text
    assert (await email_rows(world, order_id))["order_shipped"] == ("sent", 0, True)


async def test_a_fulfilment_publish_failure_still_fulfils(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    enqueuer: RecordingEnqueuer,
) -> None:
    order_id, _ = await pay(client, world, stripe)
    enqueuer.fail = True

    response = await fulfil(client, world, order_id)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "fulfilled"
    assert (await email_rows(world, order_id))["order_shipped"] == ("pending", 0, False)


async def test_logs_never_carry_an_address_subject_or_body(
    client: AsyncClient,
    world: World,
    stripe: FakeStripeCheckout,
    sender: RecordingSender,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    order_id, _ = await pay(client, world, stripe)
    sender.errors["dana@x.test"] = EmailDisabled()
    for kind in ("order_confirmation", "new_order_alert"):
        await send(client, job(world, order_id, kind))
    await fulfil(client, world, order_id)
    await send(client, job(world, order_id, "order_shipped"))

    logged = caplog.text + " ".join(str(vars(r)) for r in caplog.records)
    assert sender.sent
    for message in sender.sent:
        assert message.to not in logged
        assert message.subject not in logged
        assert message.text not in logged
    assert order_id in logged
