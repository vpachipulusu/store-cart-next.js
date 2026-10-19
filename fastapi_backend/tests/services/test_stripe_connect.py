"""Connect service, webhook service and the checkout guard with in-memory fakes (KAN-67)."""

from typing import Any

import pytest

from app.core.stripe_billing import StripeError
from app.core.stripe_connect import StripeAccountState
from app.models.platform.membership import MembershipRole
from app.services.org_billing import (
    BillingForbidden,
    BillingUnavailable,
    InvalidReturnUrl,
    OrganizationNotFound,
    allowed_origins,
)
from app.services.stripe_connect import (
    ChargesNotEnabled,
    ConnectService,
    ConnectWebhookService,
    MalformedConnectEvent,
    WebhookOutcome,
    require_charges_enabled,
    require_org_charges_enabled,
)
from tests.fakes_billing import FakeCommitSession
from tests.fakes_connect import FakeConnectStore, FakeStripeConnect, connect_record

OK = "https://app.example.com/settings"
ENABLED = StripeAccountState(
    charges_enabled=True, payouts_enabled=False, details_submitted=True
)


def build(
    record: Any = None,
) -> tuple[ConnectService, FakeConnectStore, FakeStripeConnect, FakeCommitSession]:
    store = FakeConnectStore()
    store.add(record or connect_record(), "owner", MembershipRole.OWNER)
    store.roles[("org1", "admin")] = MembershipRole.ADMIN
    store.roles[("org1", "staff")] = MembershipRole.STAFF
    stripe = FakeStripeConnect()
    session = FakeCommitSession()
    service = ConnectService(
        store,
        store,
        session,  # type: ignore[arg-type]
        stripe,
        allowed_origins("https://app.example.com"),
    )
    return service, store, stripe, session


async def onboard(service: ConnectService, user: str = "owner", **overrides: Any):
    args = {"return_url": OK, "refresh_url": OK}
    return await service.start_onboarding("org1", user, **{**args, **overrides})


async def test_first_onboarding_creates_and_saves_the_account_then_links_it():
    service, store, stripe, session = build()

    url = await onboard(service)

    assert url == "https://connect.stripe.test/setup/abc"
    assert stripe.names() == ["create_account", "create_account_link"]
    assert stripe.last("create_account")["idempotency_key"] == "sc-connect-account-org1"
    assert stripe.last("create_account_link")["account_id"] == "acct_new"
    assert store.orgs["org1"].stripe_connect_account_id == "acct_new"
    assert session.commits == 1


async def test_continue_onboarding_reuses_the_saved_account():
    service, _, stripe, _ = build(connect_record(stripe_connect_account_id="acct_1"))

    await onboard(service)

    assert stripe.names() == ["create_account_link"]
    assert stripe.last("create_account_link")["account_id"] == "acct_1"


async def test_every_link_request_uses_a_fresh_server_side_idempotency_key():
    service, _, stripe, _ = build(connect_record(stripe_connect_account_id="acct_1"))

    await onboard(service)
    await onboard(service)

    keys = [
        args["idempotency_key"]
        for name, args in stripe.calls
        if name == "create_account_link"
    ]
    assert len(set(keys)) == 2
    assert all(key.startswith("sc-connect-link-org1-") for key in keys)


async def test_admin_may_onboard_but_staff_and_strangers_may_not():
    service, _, stripe, _ = build()

    assert await onboard(service, "admin")
    with pytest.raises(BillingForbidden):
        await onboard(service, "staff")
    with pytest.raises(OrganizationNotFound):
        await onboard(service, "nobody")
    assert stripe.names().count("create_account") == 1


@pytest.mark.parametrize("field", ["return_url", "refresh_url"])
@pytest.mark.parametrize("url", ["https://evil.example.com/", "javascript:alert(1)"])
async def test_foreign_return_or_refresh_urls_are_rejected_before_stripe(field, url):
    service, _, stripe, _ = build()

    with pytest.raises(InvalidReturnUrl):
        await onboard(service, **{field: url})

    assert stripe.calls == []


async def test_account_creation_failure_saves_nothing():
    service, store, stripe, session = build()
    stripe.fail_on = "create_account"

    with pytest.raises(BillingUnavailable):
        await onboard(service)

    assert store.orgs["org1"].stripe_connect_account_id is None
    assert session.commits == 0


async def test_link_failure_keeps_the_account_linked_and_committed():
    service, store, stripe, session = build()
    stripe.fail_on = "create_account_link"

    with pytest.raises(BillingUnavailable):
        await onboard(service)

    assert store.orgs["org1"].stripe_connect_account_id == "acct_new"
    assert session.commits == 1


async def test_a_retry_after_a_failed_link_reuses_the_saved_account():
    service, _, stripe, _ = build()
    stripe.fail_on = "create_account_link"
    with pytest.raises(BillingUnavailable):
        await onboard(service)
    stripe.fail_on = None

    assert await onboard(service)

    assert stripe.names().count("create_account") == 1


async def test_an_in_flight_conflict_is_retried_and_creates_the_account_once():
    service, store, stripe, session = build()
    stripe.reject_next_create = True

    url = await onboard(service)

    assert url == "https://connect.stripe.test/setup/abc"
    assert stripe.names().count("create_account") == 2
    assert store.orgs["org1"].stripe_connect_account_id == "acct_new"
    assert session.commits == 1


async def test_a_conflict_uses_the_account_the_racing_request_already_linked():
    service, store, stripe, _ = build()
    stripe.reject_next_create = True
    original = store.get
    calls = 0

    async def get_then_link(organization_id: str):
        nonlocal calls
        calls += 1
        if calls == 2:  # the re-read after the conflict: the other request has linked
            await store.link_account(organization_id, "acct_winner")
        return await original(organization_id)

    store.get = get_then_link  # type: ignore[method-assign]

    await onboard(service)

    assert stripe.names().count("create_account") == 1
    assert stripe.last("create_account_link")["account_id"] == "acct_winner"


async def test_repeated_conflicts_become_billing_unavailable():
    service, _, stripe, _ = build()

    async def always_reject(**kwargs: Any) -> str:
        from app.core.stripe_billing import StripeRejected

        raise StripeRejected("Stripe request failed")

    stripe.create_account = always_reject  # type: ignore[method-assign]

    with pytest.raises(BillingUnavailable):
        await onboard(service)


async def test_organisation_deleted_during_account_link_is_not_found_and_rolls_back():
    service, store, _, session = build()

    async def vanished(organization_id: str, account_id: str) -> str:
        raise LookupError

    store.link_account = vanished  # type: ignore[method-assign]

    with pytest.raises(OrganizationNotFound):
        await onboard(service)

    assert session.rollbacks >= 2
    assert session.commits == 0


async def test_status_reports_the_stored_flags_to_owner_and_admin():
    service, _, _, _ = build(
        connect_record(
            stripe_connect_account_id="acct_1",
            connect_charges_enabled=True,
            connect_details_submitted=True,
        )
    )

    status = await service.status("org1", "admin")

    assert (
        status.has_account,
        status.charges_enabled,
        status.payouts_enabled,
        status.details_submitted,
    ) == (True, True, False, True)


async def test_status_for_an_unknown_organisation_or_non_member_is_not_found():
    service, store, _, _ = build()
    store.roles[("ghost", "owner")] = MembershipRole.OWNER

    with pytest.raises(OrganizationNotFound):
        await service.status("ghost", "owner")
    with pytest.raises(OrganizationNotFound):
        await service.status("org1", "nobody")
    with pytest.raises(BillingForbidden):
        await service.status("org1", "staff")


def updated_event(account_id: str = "acct_1", **payload: Any) -> dict[str, Any]:
    """An account.updated event; the payload flags are deliberately not what the service uses."""
    return {
        "id": "evt_1",
        "type": "account.updated",
        "created": 1_800_000_000,
        "data": {"object": {"id": account_id, **payload}},
    }


def deauthorized_event(account: Any = "acct_1") -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": "evt_2",
        "type": "account.application.deauthorized",
        "created": 1_800_000_000,
        "data": {"object": {"id": "ca_platform", "object": "application"}},
    }
    if account is not None:
        event["account"] = account
    return event


def webhook() -> tuple[
    ConnectWebhookService, FakeConnectStore, FakeStripeConnect, FakeCommitSession
]:
    store = FakeConnectStore()
    store.add(
        connect_record(stripe_connect_account_id="acct_1"),
        "owner",
        MembershipRole.OWNER,
    )
    stripe = FakeStripeConnect()
    session = FakeCommitSession()
    service = ConnectWebhookService(store, session, lambda: stripe)  # type: ignore[arg-type]
    return service, store, stripe, session


async def test_account_updated_stores_the_flags_stripe_reports_now():
    service, store, stripe, session = webhook()
    stripe.account_state = ENABLED

    outcome = await service.handle(updated_event())

    record = store.orgs["org1"]
    assert outcome is WebhookOutcome.PROCESSED
    assert (
        record.connect_charges_enabled,
        record.connect_payouts_enabled,
        record.connect_details_submitted,
    ) == (True, False, True)
    assert stripe.last("get_account") == {"account_id": "acct_1"}
    assert session.commits == 1


async def test_the_payload_flags_are_ignored_so_a_stale_event_cannot_win():
    service, store, stripe, _ = webhook()
    stripe.account_state = ENABLED
    stale = updated_event(
        charges_enabled=False, payouts_enabled=False, details_submitted=False
    )

    await service.handle(stale)  # delivered late, carrying older state
    await service.handle(
        updated_event(charges_enabled=True)
    )  # same second, reversed order

    assert store.orgs["org1"].connect_charges_enabled is True


async def test_charges_follow_stripe_when_they_are_later_switched_off():
    service, store, stripe, _ = webhook()
    stripe.account_state = ENABLED
    await service.handle(updated_event())

    stripe.account_state = StripeAccountState(False, False, True)
    await service.handle(updated_event())

    assert store.orgs["org1"].connect_charges_enabled is False


async def test_a_read_that_started_earlier_cannot_overwrite_a_newer_one():
    service, store, stripe, _ = webhook()
    stripe.account_state = ENABLED
    await service.handle(updated_event())
    from datetime import UTC, datetime

    outcome = await service._apply(
        "acct_1",
        StripeAccountState(False, False, False),
        datetime(2020, 1, 1, tzinfo=UTC),
    )

    assert outcome is WebhookOutcome.IGNORED
    assert store.orgs["org1"].connect_charges_enabled is True


async def test_redelivery_is_idempotent():
    service, store, stripe, _ = webhook()
    stripe.account_state = ENABLED

    await service.handle(updated_event())
    await service.handle(updated_event())

    assert store.orgs["org1"].connect_charges_enabled is True


async def test_deauthorization_clears_the_flags_without_calling_stripe():
    service, store, stripe, _ = webhook()
    stripe.account_state = ENABLED
    await service.handle(updated_event())

    outcome = await service.handle(deauthorized_event())

    record = store.orgs["org1"]
    assert outcome is WebhookOutcome.PROCESSED
    assert (
        record.connect_charges_enabled,
        record.connect_payouts_enabled,
        record.connect_details_submitted,
    ) == (False, False, False)
    assert stripe.names() == ["get_account"]


async def test_an_account_stripe_no_longer_knows_has_its_flags_cleared():
    service, store, stripe, _ = webhook()
    stripe.account_state = ENABLED
    await service.handle(updated_event())
    stripe.not_found_on_get = True

    await service.handle(updated_event())

    assert store.orgs["org1"].connect_charges_enabled is False


async def test_a_stripe_outage_propagates_so_the_event_is_retried():
    service, store, stripe, session = webhook()
    stripe.fail_on = "get_account"

    with pytest.raises(StripeError):
        await service.handle(updated_event())

    assert store.orgs["org1"].connect_charges_enabled is False
    assert session.commits == 0


async def test_unknown_account_is_ignored_not_retried():
    service, _, _, _ = webhook()

    assert await service.handle(updated_event("acct_other")) is WebhookOutcome.IGNORED
    assert (
        await service.handle(deauthorized_event("acct_other")) is WebhookOutcome.IGNORED
    )


async def test_other_event_types_are_ignored_without_touching_stripe_or_the_store():
    service, store, stripe, session = webhook()

    outcome = await service.handle({"id": "evt_3", "type": "customer.updated"})

    assert outcome is WebhookOutcome.IGNORED
    assert stripe.calls == []
    assert store.orgs["org1"].connect_charges_enabled is False
    assert session.commits == 0


@pytest.mark.parametrize(
    "event",
    [
        {"type": "account.updated", "created": 1},
        {"type": "account.updated", "data": {"object": "x"}},
        {"type": "account.updated", "data": {"object": {"id": ""}}},
        {"type": "account.updated", "data": {"object": {"id": 5}}},
        {"type": "account.application.deauthorized", "data": {"object": {}}},
        {"type": "account.application.deauthorized", "account": ""},
        {"type": "account.application.deauthorized", "account": 7},
    ],
)
async def test_events_without_an_account_id_are_rejected(event):
    service, _, stripe, _ = webhook()

    with pytest.raises(MalformedConnectEvent):
        await service.handle(event)

    assert stripe.calls == []


def test_guard_blocks_without_an_account_or_with_charges_disabled():
    with pytest.raises(ChargesNotEnabled):
        require_charges_enabled(connect_record())
    with pytest.raises(ChargesNotEnabled):
        require_charges_enabled(connect_record(stripe_connect_account_id="acct_1"))
    with pytest.raises(ChargesNotEnabled):
        require_charges_enabled(connect_record(connect_charges_enabled=True))


def test_guard_allows_an_account_with_charges_enabled():
    require_charges_enabled(
        connect_record(stripe_connect_account_id="acct_1", connect_charges_enabled=True)
    )


async def test_org_guard_loads_the_organisation_and_blocks_unknown_ones():
    store = FakeConnectStore()
    store.orgs["ready"] = connect_record(
        id="ready", stripe_connect_account_id="acct_1", connect_charges_enabled=True
    )
    store.orgs["new"] = connect_record(id="new")

    await require_org_charges_enabled(store, "ready")
    with pytest.raises(ChargesNotEnabled):
        await require_org_charges_enabled(store, "new")
    with pytest.raises(ChargesNotEnabled):
        await require_org_charges_enabled(store, "missing")
