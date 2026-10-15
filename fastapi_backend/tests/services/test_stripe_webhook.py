from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.plans import PlanKey
from app.repositories.billing import BillingChange, BillingState
from app.services.stripe_webhook import (
    MalformedEvent,
    StripeWebhookService,
    WebhookOutcome,
    parse_subscription,
    plan_change,
)

PRO_PRICE = "price_pro_monthly"
ENT_PRICE = "price_ent_monthly"
PRICES = {PRO_PRICE: PlanKey.PRO, ENT_PRICE: PlanKey.ENTERPRISE}
T0 = 1_800_000_000


def at(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, tz=UTC)


def subscription(
    status: str = "active",
    *,
    sub_id: str = "sub_1",
    customer: Any = "cus_1",
    price: str | None = PRO_PRICE,
    period_end: int | None = T0 + 1000,
    item_period_end: int | None = None,
    cancel_at_period_end: Any = None,
    cancel_at: Any = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {"price": {"id": price}} if price else {}
    if item_period_end is not None:
        item["current_period_end"] = item_period_end
    body: dict[str, Any] = {
        "id": sub_id,
        "customer": customer,
        "status": status,
        "items": {"data": [item]},
    }
    if period_end is not None:
        body["current_period_end"] = period_end
    if cancel_at_period_end is not None:
        body["cancel_at_period_end"] = cancel_at_period_end
    if cancel_at is not None:
        body["cancel_at"] = cancel_at
    return body


def event(
    event_id: str = "evt_1",
    event_type: str = "customer.subscription.updated",
    created: int = T0,
    obj: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": event_id,
        "type": event_type,
        "created": created,
        "data": {"object": obj if obj is not None else subscription()},
    }


def state(**overrides: Any) -> BillingState:
    values: dict[str, Any] = {
        "organization_id": "org_1",
        "stripe_subscription_id": None,
        "stripe_price_id": None,
        "stripe_current_period_end": None,
        "stripe_subscription_event_at": None,
        "subscription_tier": "free",
        "subscription_status": "inactive",
    }
    return BillingState(**{**values, **overrides})


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeEvents:
    def __init__(self) -> None:
        self.seen: set[str] = set()

    async def claim(
        self, stripe_event_id: str, event_type: str, created: datetime
    ) -> bool:
        if stripe_event_id in self.seen:
            return False
        self.seen.add(stripe_event_id)
        return True


class FakeOrgs:
    def __init__(self, current: BillingState | None, fail: bool = False) -> None:
        self.current = current
        self.fail = fail
        self.lookups: list[tuple[str | None, str | None]] = []
        self.applied: list[BillingChange] = []

    async def get_for_update(
        self, *, subscription_id: str | None, customer_id: str | None
    ) -> BillingState | None:
        self.lookups.append((subscription_id, customer_id))
        return self.current

    async def apply(self, organization_id: str, change: BillingChange) -> None:
        if self.fail:
            raise RuntimeError("db down")
        self.applied.append(change)


def build(current: BillingState | None = None, fail: bool = False):
    session, events, orgs = FakeSession(), FakeEvents(), FakeOrgs(current, fail)
    service = StripeWebhookService(events, orgs, session, PRICES)  # type: ignore[arg-type]
    return service, session, events, orgs


async def test_applies_a_subscription_and_commits_once():
    service, session, _events, orgs = build(state())

    outcome = await service.handle(event())

    assert outcome is WebhookOutcome.PROCESSED
    assert session.commits == 1 and session.rollbacks == 0
    assert orgs.applied == [
        BillingChange("sub_1", PRO_PRICE, at(T0 + 1000), at(T0), "pro", "active")
    ]
    assert orgs.lookups == [("sub_1", "cus_1")]


async def test_duplicate_event_changes_nothing():
    service, _session, _events, orgs = build(state())
    await service.handle(event())

    outcome = await service.handle(event())

    assert outcome is WebhookOutcome.DUPLICATE
    assert len(orgs.applied) == 1


async def test_unknown_event_type_is_ignored_without_touching_anything():
    service, session, events, orgs = build(state())

    outcome = await service.handle(event(event_type="invoice.paid"))

    assert outcome is WebhookOutcome.IGNORED
    assert not events.seen and not orgs.lookups and session.commits == 0


async def test_failed_apply_rolls_back_and_does_not_commit():
    service, session, _events, _orgs = build(state(), fail=True)

    with pytest.raises(RuntimeError):
        await service.handle(event())

    assert session.rollbacks == 1 and session.commits == 0


async def test_event_for_unknown_organisation_is_rolled_back_not_recorded():
    service, session, _events, orgs = build(None)

    outcome = await service.handle(event())

    assert outcome is WebhookOutcome.UNMATCHED
    assert not orgs.applied and session.commits == 0 and session.rollbacks == 1


async def test_older_event_does_not_overwrite_a_newer_one():
    current = state(stripe_subscription_event_at=at(T0 + 50), subscription_tier="pro")
    service, _session, _events, orgs = build(current)

    outcome = await service.handle(
        event(created=T0, obj=subscription("canceled", price=None))
    )

    assert outcome is WebhookOutcome.PROCESSED
    assert orgs.applied == []


async def test_event_with_the_same_time_is_applied():
    current = state(stripe_subscription_event_at=at(T0))
    service, _session, _events, orgs = build(current)

    await service.handle(event(created=T0))

    assert len(orgs.applied) == 1


@pytest.mark.parametrize("bad", [{}, {"id": "evt"}, {"id": "evt", "type": "x"}])
async def test_event_without_id_type_or_created_is_malformed(bad):
    service, session, *_ = build(state())

    with pytest.raises(MalformedEvent):
        await service.handle(bad)

    assert session.commits == 0


@pytest.mark.parametrize(
    "payload", [{}, {"data": None}, {"data": {}}, {"data": {"object": "x"}}]
)
async def test_subscription_event_without_an_object_is_malformed(payload):
    service, *_ = build(state())
    body = {"id": "evt", "type": "customer.subscription.updated", "created": T0}

    with pytest.raises(MalformedEvent):
        await service.handle({**body, **payload})


async def test_subscription_without_id_or_status_is_malformed():
    service, *_ = build(state())

    with pytest.raises(MalformedEvent):
        await service.handle(event(obj={"id": "sub_1"}))


def test_parse_reads_period_end_from_the_item_in_newer_api_versions():
    parsed = parse_subscription(subscription(period_end=None, item_period_end=T0 + 7))

    assert parsed.period_end == at(T0 + 7)


def test_parse_accepts_an_expanded_customer_object():
    parsed = parse_subscription(subscription(customer={"id": "cus_9"}))

    assert parsed.customer_id == "cus_9"


def test_parse_tolerates_missing_items_and_customer():
    parsed = parse_subscription({"id": "sub_1", "status": "active"})

    assert (parsed.price_id, parsed.customer_id, parsed.period_end) == (
        None,
        None,
        None,
    )


def test_parse_ignores_an_out_of_range_timestamp():
    assert parse_subscription(subscription(period_end=10**30)).period_end is None


def test_parse_truncates_an_oversized_status():
    assert len(parse_subscription(subscription("x" * 100)).status) == 32


@pytest.mark.parametrize(
    ("price", "tier"), [(PRO_PRICE, "pro"), (ENT_PRICE, "enterprise")]
)
@pytest.mark.parametrize("status", ["active", "trialing", "past_due"])
def test_entitled_status_sets_the_tier_from_the_price(status, price, tier):
    change = plan_change(
        "customer.subscription.updated",
        at(T0),
        parse_subscription(subscription(status, price=price)),
        state(),
        PRICES,
    )

    assert change is not None and change.subscription_tier == tier
    assert change.subscription_status == status


@pytest.mark.parametrize(
    "status", ["canceled", "unpaid", "incomplete_expired", "paused"]
)
def test_ended_status_downgrades_to_free_and_clears_the_price(status):
    change = plan_change(
        "customer.subscription.updated",
        at(T0),
        parse_subscription(subscription(status)),
        state(stripe_subscription_id="sub_1", subscription_tier="pro"),
        PRICES,
    )

    assert change is not None
    assert (change.subscription_tier, change.stripe_price_id) == ("free", None)


def test_deleted_event_marks_the_subscription_canceled():
    change = plan_change(
        "customer.subscription.deleted",
        at(T0),
        parse_subscription(subscription("active")),
        state(stripe_subscription_id="sub_1", subscription_tier="pro"),
        PRICES,
    )

    assert change is not None
    assert (change.subscription_status, change.subscription_tier) == (
        "canceled",
        "free",
    )


def test_incomplete_status_keeps_the_current_tier():
    change = plan_change(
        "customer.subscription.created",
        at(T0),
        parse_subscription(subscription("incomplete")),
        state(subscription_tier="free"),
        PRICES,
    )

    assert change is not None
    assert (change.subscription_tier, change.subscription_status) == (
        "free",
        "incomplete",
    )


def test_unmapped_price_keeps_the_current_tier():
    change = plan_change(
        "customer.subscription.updated",
        at(T0),
        parse_subscription(subscription(price="price_unknown")),
        state(subscription_tier="pro"),
        PRICES,
    )

    assert change is not None and change.subscription_tier == "pro"


def test_missing_price_on_an_active_subscription_keeps_the_tier():
    change = plan_change(
        "customer.subscription.updated",
        at(T0),
        parse_subscription(subscription(price=None)),
        state(subscription_tier="pro"),
        PRICES,
    )

    assert change is not None and change.subscription_tier == "pro"


def test_old_subscription_ending_does_not_downgrade_the_new_one():
    change = plan_change(
        "customer.subscription.deleted",
        at(T0),
        parse_subscription(subscription("canceled", sub_id="sub_old")),
        state(stripe_subscription_id="sub_new", subscription_tier="pro"),
        PRICES,
    )

    assert change is None


def test_a_new_active_subscription_replaces_the_old_one():
    change = plan_change(
        "customer.subscription.created",
        at(T0),
        parse_subscription(subscription("active", sub_id="sub_new")),
        state(stripe_subscription_id="sub_old", subscription_tier="free"),
        PRICES,
    )

    assert change is not None
    assert (change.stripe_subscription_id, change.subscription_tier) == (
        "sub_new",
        "pro",
    )


def test_incomplete_new_subscription_does_not_replace_an_active_one():
    change = plan_change(
        "customer.subscription.created",
        at(T0),
        parse_subscription(subscription("incomplete", sub_id="sub_new")),
        state(stripe_subscription_id="sub_old", subscription_tier="pro"),
        PRICES,
    )

    assert change is None


def test_created_event_from_the_same_second_as_an_update_is_ignored():
    change = plan_change(
        "customer.subscription.created",
        at(T0),
        parse_subscription(subscription("incomplete")),
        state(
            stripe_subscription_id="sub_1",
            stripe_subscription_event_at=at(T0),
            subscription_tier="pro",
            subscription_status="active",
        ),
        PRICES,
    )

    assert change is None


def test_late_active_update_does_not_resurrect_a_subscription_ended_in_the_same_second():
    change = plan_change(
        "customer.subscription.updated",
        at(T0),
        parse_subscription(subscription("active")),
        state(
            stripe_subscription_id="sub_1",
            stripe_subscription_event_at=at(T0),
            subscription_status="canceled",
        ),
        PRICES,
    )

    assert change is None


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({}, False),
        ({"cancel_at_period_end": False}, False),
        ({"cancel_at_period_end": True}, True),
        ({"cancel_at": T0 + 5000}, True),
        ({"cancel_at_period_end": False, "cancel_at": T0 + 5000}, True),
        ({"cancel_at_period_end": "true"}, False),
        ({"cancel_at": "soon"}, False),
    ],
)
def test_parse_reads_the_cancellation_flag_with_cancel_at_as_fallback(fields, expected):
    assert parse_subscription(subscription(**fields)).cancel_at_period_end is expected


def _flag(event_type: str, status: str) -> bool:
    change = plan_change(
        event_type,
        at(T0),
        parse_subscription(subscription(status, cancel_at_period_end=True)),
        state(stripe_subscription_id="sub_1", subscription_tier="pro"),
        PRICES,
    )
    assert change is not None
    return change.stripe_cancel_at_period_end


def test_flag_is_stored_for_a_live_subscription():
    assert _flag("customer.subscription.updated", "active") is True


@pytest.mark.parametrize(
    ("event_type", "status"),
    [
        ("customer.subscription.deleted", "active"),
        ("customer.subscription.updated", "canceled"),
    ],
)
def test_flag_is_cleared_once_the_subscription_has_ended(event_type, status):
    assert _flag(event_type, status) is False


def test_flag_respects_the_stale_event_rule():
    change = plan_change(
        "customer.subscription.updated",
        at(T0 - 1),
        parse_subscription(subscription(cancel_at_period_end=True)),
        state(stripe_subscription_event_at=at(T0), stripe_subscription_id="sub_1"),
        PRICES,
    )

    assert change is None
