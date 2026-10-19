"""Connect webhook routing and at-most-once processing with in-memory fakes (KAN-69)."""

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from app.core.stripe_billing import StripeError
from app.core.stripe_connect import StripeAccountState
from app.models.platform.membership import MembershipRole
from app.services.stripe_connect import (
    ConnectRoute,
    ConnectWebhookService,
    MalformedConnectEvent,
    WebhookOutcome,
)
from tests.fakes_connect import (
    FakeConnectEvents,
    FakeConnectStore,
    FakeEventSession,
    FakeStripeConnect,
    connect_record,
)

PAID = "checkout.session.completed"
ENABLED = StripeAccountState(True, True, True)


class RecordingHandler:
    """A store-scoped handler that records the route and object it was given."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[ConnectRoute, Mapping[str, Any]]] = []
        self.error = error

    async def __call__(self, route: ConnectRoute, obj: Mapping[str, Any]) -> None:
        self.calls.append((route, obj))
        if self.error is not None:
            raise self.error


def build(
    handler: RecordingHandler | None = None,
) -> tuple[
    ConnectWebhookService,
    FakeConnectStore,
    FakeConnectEvents,
    FakeStripeConnect,
    FakeEventSession,
]:
    store = FakeConnectStore()
    for org, account in (("org1", "acct_1"), ("org2", "acct_2")):
        store.add(
            connect_record(id=org, stripe_connect_account_id=account),
            f"owner-{org}",
            MembershipRole.OWNER,
        )
    store.stores = {"store1": "org1", "store2": "org2"}
    events = FakeConnectEvents()
    session = FakeEventSession(events)
    stripe = FakeStripeConnect()
    handlers = {PAID: handler} if handler is not None else {}
    service = ConnectWebhookService(
        store,
        events,
        session,  # type: ignore[arg-type]
        lambda: stripe,
        store_handlers=handlers,
    )
    return service, store, events, stripe, session


def store_event(
    event_id: str = "evt_pay1",
    account: Any = "acct_1",
    metadata: Any = None,
) -> dict[str, Any]:
    obj: dict[str, Any] = {"id": "cs_1", "object": "checkout.session"}
    obj["metadata"] = {"store_id": "store1"} if metadata is None else metadata
    event: dict[str, Any] = {
        "id": event_id,
        "type": PAID,
        "created": 1_800_000_000,
        "data": {"object": obj},
    }
    if account is not None:
        event["account"] = account
    return event


def updated_event(event_id: str = "evt_upd1", account: str = "acct_1"):
    return {
        "id": event_id,
        "type": "account.updated",
        "created": 1_800_000_000,
        "account": account,
        "data": {"object": {"id": account}},
    }


# Routing


async def test_a_store_event_is_routed_to_the_organisation_and_store_it_belongs_to():
    handler = RecordingHandler()
    service, _, events, _, session = build(handler)

    outcome = await service.handle(store_event())

    assert outcome is WebhookOutcome.PROCESSED
    route, obj = handler.calls[0]
    assert route == ConnectRoute(
        organization_id="org1", account_id="acct_1", store_id="store1"
    )
    assert obj["id"] == "cs_1"
    assert events.recorded["evt_pay1"].route == route
    assert session.commits == 1


async def test_the_connected_account_picks_the_organisation_not_the_metadata():
    handler = RecordingHandler()
    service, _, _, _, _ = build(handler)

    outcome = await service.handle(
        store_event(account="acct_2", metadata={"store_id": "store2"})
    )

    assert outcome is WebhookOutcome.PROCESSED
    assert handler.calls[0][0].organization_id == "org2"


async def test_metadata_naming_another_organisations_store_is_ignored(caplog):
    handler = RecordingHandler()
    service, _, events, _, session = build(handler)

    # Signed by Stripe for acct_1, but the metadata claims org2's store.
    outcome = await service.handle(store_event(metadata={"store_id": "store2"}))

    assert outcome is WebhookOutcome.IGNORED
    assert handler.calls == [] and events.recorded == {}
    assert session.commits == 0
    assert "store2" not in caplog.text


@pytest.mark.parametrize("metadata", [{}, {"store_id": ""}, {"store_id": 7}, "x"])
async def test_a_store_event_without_a_usable_store_id_is_ignored(metadata):
    handler = RecordingHandler()
    service, _, events, _, _ = build(handler)

    outcome = await service.handle(store_event(metadata=metadata))

    assert outcome is WebhookOutcome.IGNORED
    assert handler.calls == [] and events.recorded == {}


async def test_an_unknown_store_id_is_ignored():
    handler = RecordingHandler()
    service, _, events, _, _ = build(handler)

    outcome = await service.handle(store_event(metadata={"store_id": "nope"}))

    assert outcome is WebhookOutcome.IGNORED
    assert handler.calls == [] and events.recorded == {}


async def test_an_event_for_an_unknown_account_is_acknowledged_and_not_recorded(
    caplog,
):
    handler = RecordingHandler()
    service, _, events, stripe, session = build(handler)

    store_outcome = await service.handle(store_event(account="acct_nobody"))
    account_outcome = await service.handle(updated_event(account="acct_nobody"))

    assert (store_outcome, account_outcome) == (
        WebhookOutcome.IGNORED,
        WebhookOutcome.IGNORED,
    )
    assert handler.calls == [] and stripe.calls == [] and events.recorded == {}
    assert session.commits == 0
    assert "unknown account" in caplog.text
    assert "acct_nobody" not in caplog.text


async def test_a_store_event_without_a_connected_account_is_rejected():
    handler = RecordingHandler()
    service, _, _, _, _ = build(handler)

    with pytest.raises(MalformedConnectEvent):
        await service.handle(store_event(account=None))

    assert handler.calls == []


async def test_account_updated_whose_account_disagrees_with_its_object_is_rejected():
    service, _, _, stripe, _ = build()
    event = updated_event()
    event["data"]["object"]["id"] = "acct_2"

    with pytest.raises(MalformedConnectEvent):
        await service.handle(event)

    assert stripe.calls == []


async def test_account_events_are_recorded_against_the_organisation():
    service, store, events, stripe, _ = build()
    stripe.account_state = ENABLED

    await service.handle(updated_event(account="acct_2"))

    assert events.recorded["evt_upd1"].route == ConnectRoute("org2", "acct_2", None)
    assert store.orgs["org2"].connect_charges_enabled is True
    assert store.orgs["org1"].connect_charges_enabled is False


async def test_unknown_event_types_are_acknowledged_without_validation_or_recording():
    service, _, events, stripe, session = build()

    outcome = await service.handle({"type": "payout.paid"})

    assert outcome is WebhookOutcome.IGNORED
    assert events.recorded == {} and stripe.calls == [] and session.commits == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": None},
        {"id": ""},
        {"id": 5},
        {"id": "pi_1"},
        {"id": "evt_1 2"},
        {"created": None},
        {"created": "soon"},
        {"created": True},
    ],
)
async def test_a_handled_event_without_an_id_or_created_time_is_rejected(overrides):
    handler = RecordingHandler()
    service, _, _, _, _ = build(handler)
    event = {**store_event(), **overrides}
    event = {key: value for key, value in event.items() if value is not None}

    with pytest.raises(MalformedConnectEvent):
        await service.handle(event)

    assert handler.calls == []


# At most once


async def test_a_redelivered_store_event_is_handled_once():
    handler = RecordingHandler()
    service, _, _, _, session = build(handler)

    first = await service.handle(store_event())
    second = await service.handle(store_event())

    assert (first, second) == (WebhookOutcome.PROCESSED, WebhookOutcome.DUPLICATE)
    assert len(handler.calls) == 1
    assert session.commits == 1


async def test_a_redelivered_account_event_does_not_call_stripe_again():
    service, _, _, stripe, _ = build()
    stripe.account_state = ENABLED

    first = await service.handle(updated_event())
    second = await service.handle(updated_event())

    assert (first, second) == (WebhookOutcome.PROCESSED, WebhookOutcome.DUPLICATE)
    assert stripe.names() == ["get_account"]


async def test_concurrent_deliveries_of_one_event_are_handled_once():
    handler = RecordingHandler()
    service, _, events, _, _ = build(handler)

    outcomes = await asyncio.gather(*(service.handle(store_event()) for _ in range(4)))

    assert sorted(outcomes) == sorted(
        [WebhookOutcome.PROCESSED] + [WebhookOutcome.DUPLICATE] * 3
    )
    assert len(handler.calls) == 1
    assert list(events.recorded) == ["evt_pay1"]


async def test_concurrent_account_deliveries_that_both_read_stripe_apply_once():
    service, _, events, stripe, session = build()
    stripe.account_state = ENABLED

    # Both pass the cheap pre-check before either claims; the claim decides.
    outcomes = await asyncio.gather(
        service.handle(updated_event()), service.handle(updated_event())
    )

    assert sorted(outcomes) == sorted(
        [WebhookOutcome.PROCESSED, WebhookOutcome.DUPLICATE]
    )
    assert list(events.recorded) == ["evt_upd1"]
    assert session.commits == 1


async def test_a_failing_handler_leaves_the_event_unrecorded_so_stripe_retries():
    handler = RecordingHandler(RuntimeError("boom"))
    service, _, events, _, session = build(handler)

    with pytest.raises(RuntimeError):
        await service.handle(store_event())
    handler.error = None
    retried = await service.handle(store_event())

    assert retried is WebhookOutcome.PROCESSED
    assert len(handler.calls) == 2
    assert list(events.recorded) == ["evt_pay1"]
    assert session.rollbacks >= 1


async def test_a_stripe_outage_leaves_the_account_event_unrecorded():
    service, _, events, stripe, _ = build()
    stripe.fail_on = "get_account"

    with pytest.raises(StripeError):
        await service.handle(updated_event())

    assert events.recorded == {} and events.pending == {}


async def test_a_deauthorization_is_recorded_once():
    service, store, events, stripe, _ = build()
    event = {
        "id": "evt_de1",
        "type": "account.application.deauthorized",
        "created": 1_800_000_000,
        "account": "acct_1",
        "data": {"object": {"id": "ca_platform"}},
    }

    outcomes = [await service.handle(event), await service.handle(event)]

    assert outcomes == [WebhookOutcome.PROCESSED, WebhookOutcome.DUPLICATE]
    assert events.recorded["evt_de1"].route == ConnectRoute("org1", "acct_1", None)
    assert stripe.calls == []
    assert store.orgs["org1"].connect_charges_enabled is False


def test_account_events_cannot_be_registered_as_store_scoped():
    store, events = FakeConnectStore(), FakeConnectEvents()

    with pytest.raises(ValueError):
        ConnectWebhookService(
            store,
            events,
            FakeEventSession(events),  # type: ignore[arg-type]
            FakeStripeConnect,
            store_handlers={"account.updated": RecordingHandler()},
        )
