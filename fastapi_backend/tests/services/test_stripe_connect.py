"""Connect service, webhook service and the checkout guard with in-memory fakes (KAN-67)."""

from typing import Any

import pytest

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
    args = {"return_url": OK, "refresh_url": OK, "request_key": "key-0001"}
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
    assert stripe.last("create_account_link")["idempotency_key"] == (
        "sc-connect-link-org1-key-0001"
    )


async def test_onboarding_without_a_request_key_still_gets_a_unique_link_key():
    service, _, stripe, _ = build(connect_record(stripe_connect_account_id="acct_1"))

    await onboard(service, request_key=None)

    assert stripe.last("create_account_link")["idempotency_key"].startswith(
        "sc-connect-link-org1-"
    )


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


@pytest.mark.parametrize("failing", ["create_account", "create_account_link"])
async def test_stripe_failures_become_billing_unavailable_and_save_nothing(failing):
    service, store, stripe, _ = build()
    stripe.fail_on = failing

    with pytest.raises(BillingUnavailable):
        await onboard(service)

    if failing == "create_account":
        assert store.orgs["org1"].stripe_connect_account_id is None


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


def account_event(**overrides: Any) -> dict[str, Any]:
    account = {
        "id": "acct_1",
        "charges_enabled": True,
        "payouts_enabled": False,
        "details_submitted": True,
    }
    event: dict[str, Any] = {
        "id": "evt_1",
        "type": "account.updated",
        "created": 1_800_000_000,
        "data": {"object": {**account, **overrides.pop("account", {})}},
    }
    return {**event, **overrides}


def webhook() -> tuple[ConnectWebhookService, FakeConnectStore, FakeCommitSession]:
    store = FakeConnectStore()
    store.add(
        connect_record(stripe_connect_account_id="acct_1"),
        "owner",
        MembershipRole.OWNER,
    )
    session = FakeCommitSession()
    return ConnectWebhookService(store, session), store, session  # type: ignore[arg-type]


async def test_account_updated_syncs_charges_and_payouts_flags():
    service, store, session = webhook()

    outcome = await service.handle(account_event())

    record = store.orgs["org1"]
    assert outcome is WebhookOutcome.PROCESSED
    assert (
        record.connect_charges_enabled,
        record.connect_payouts_enabled,
        record.connect_details_submitted,
    ) == (True, False, True)
    assert session.commits == 1


async def test_redelivery_is_idempotent():
    service, store, _ = webhook()
    event = account_event()

    await service.handle(event)
    await service.handle(event)

    assert store.orgs["org1"].connect_charges_enabled is True


async def test_an_older_event_does_not_overwrite_newer_state():
    service, store, _ = webhook()
    await service.handle(
        account_event(created=2_000, account={"charges_enabled": False})
    )

    outcome = await service.handle(account_event(created=1_000))

    assert outcome is WebhookOutcome.IGNORED
    assert store.orgs["org1"].connect_charges_enabled is False


async def test_unknown_account_is_ignored_not_retried():
    service, _, _ = webhook()

    outcome = await service.handle(account_event(account={"id": "acct_other"}))

    assert outcome is WebhookOutcome.IGNORED


async def test_other_event_types_are_ignored_without_touching_the_store():
    service, store, session = webhook()

    outcome = await service.handle({"id": "evt_2", "type": "customer.updated"})

    assert outcome is WebhookOutcome.IGNORED
    assert store.orgs["org1"].connect_charges_enabled is False
    assert session.commits == 0


@pytest.mark.parametrize(
    "event",
    [
        {"type": "account.updated", "created": 1},
        {"type": "account.updated", "created": 1, "data": {"object": "x"}},
        {"type": "account.updated", "data": {"object": {"id": "acct_1"}}},
        account_event(created="1"),
        account_event(created=True),
        account_event(account={"id": ""}),
        account_event(account={"id": 5}),
        account_event(account={"charges_enabled": "yes"}),
        account_event(account={"payouts_enabled": None}),
        account_event(account={"details_submitted": 1}),
    ],
)
async def test_malformed_account_updated_events_are_rejected(event):
    service, _, _ = webhook()

    with pytest.raises(MalformedConnectEvent):
        await service.handle(event)


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


async def test_organisation_deleted_during_account_link_is_not_found_and_rolls_back():
    service, store, _, session = build()

    async def vanished(organization_id: str, account_id: str) -> str:
        raise LookupError

    store.link_account = vanished  # type: ignore[method-assign]

    with pytest.raises(OrganizationNotFound):
        await onboard(service)

    assert session.rollbacks >= 2
    assert session.commits == 0
