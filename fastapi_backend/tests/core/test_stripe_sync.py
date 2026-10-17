"""Stripe bulk subscription lister (KAN-119): paging, parsing, and no leaked fields."""

from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.stripe_billing import StripeError
from app.core.stripe_sync import (
    PAGE_SIZE,
    HttpStripeSubscriptionLister,
    get_stripe_subscription_lister,
)

SECRET = "sk_test_unit_only_not_real"


def lister_for(
    body: dict[str, Any],
    seen: list[httpx.Request] | None = None,
    status: int = 200,
) -> HttpStripeSubscriptionLister:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HttpStripeSubscriptionLister(SECRET, client)


SUB = {
    "id": "sub_1",
    "customer": "cus_1",
    "status": "active",
    "cancel_at_period_end": False,
    "items": {"data": [{"price": {"id": "price_pro_m"}}]},
    "default_payment_method": {"card": {"last4": "4242"}},
}


async def test_asks_for_all_statuses_a_page_at_a_time_after_the_cursor():
    seen: list[httpx.Request] = []
    lister = lister_for({"data": [SUB], "has_more": False}, seen)

    await lister.list_subscriptions("sub_0")

    assert seen[0].url.path == "/v1/subscriptions"
    assert dict(seen[0].url.params) == {
        "status": "all",
        "limit": str(PAGE_SIZE),
        "starting_after": "sub_0",
    }


async def test_first_page_sends_no_cursor():
    seen: list[httpx.Request] = []

    await lister_for({"data": []}, seen).list_subscriptions(None)

    assert "starting_after" not in seen[0].url.params


async def test_keeps_only_the_fields_reconciliation_compares():
    page = await lister_for({"data": [SUB], "has_more": True}).list_subscriptions(None)

    [item] = page.items
    assert (item.id, item.customer_id, item.status) == ("sub_1", "cus_1", "active")
    assert (item.price_id, item.cancel_at_period_end) == ("price_pro_m", False)
    assert page.has_more and page.cursor == "sub_1"
    assert "4242" not in repr(page)


async def test_expanded_customer_and_scheduled_cancel_are_understood():
    row = {**SUB, "customer": {"id": "cus_2"}, "cancel_at": 1_900_000_000}

    page = await lister_for({"data": [row]}).list_subscriptions(None)

    assert page.items[0].customer_id == "cus_2"
    assert page.items[0].cancel_at_period_end is True
    assert not page.has_more


async def test_an_unusable_row_is_skipped_but_still_moves_the_cursor():
    rows = [SUB, {"id": "sub_bad"}, "junk"]

    page = await lister_for({"data": rows, "has_more": True}).list_subscriptions(None)

    assert [i.id for i in page.items] == ["sub_1"]
    assert page.cursor == "sub_bad"


async def test_row_without_items_has_no_price():
    row = {"id": "sub_2", "status": "canceled"}

    page = await lister_for({"data": [row]}).list_subscriptions(None)

    assert page.items[0].price_id is None and page.items[0].customer_id is None


async def test_has_more_without_any_row_does_not_loop_forever():
    page = await lister_for({"data": [], "has_more": True}).list_subscriptions(None)

    assert not page.has_more


async def test_stripe_error_is_a_generic_stripe_error():
    lister = lister_for({"error": {"message": "secret text"}}, status=500)

    with pytest.raises(StripeError) as raised:
        await lister.list_subscriptions(None)

    assert "secret text" not in str(raised.value)


def test_factory_needs_a_secret_key(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", None)
    assert get_stripe_subscription_lister() is None

    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", SecretStr(SECRET))
    assert isinstance(get_stripe_subscription_lister(), HttpStripeSubscriptionLister)


async def test_rows_that_cannot_be_read_are_counted_as_skipped():
    rows = [SUB, {"id": "sub_bad"}, "junk", {"status": "active"}]

    page = await lister_for({"data": rows}).list_subscriptions(None)

    assert [i.id for i in page.items] == ["sub_1"]
    assert page.skipped == 3


async def test_all_pages_of_a_sync_share_the_given_client(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", SecretStr(SECRET))
    seen: list[httpx.Request] = []
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: seen.append(r) or httpx.Response(200, json={"data": []})
        )
    )
    lister = get_stripe_subscription_lister(client)
    assert lister is not None

    await lister.list_subscriptions(None)
    await lister.list_subscriptions("sub_1")

    assert len(seen) == 2
    assert not client.is_closed
