from dataclasses import replace
from typing import Any

import pytest

from app.core.plans import PlanKey
from app.models.platform.membership import MembershipRole
from app.services.org_billing import (
    BillingConflict,
    BillingForbidden,
    BillingNotConfigured,
    BillingUnavailable,
    InvalidReturnUrl,
    OrganizationNotFound,
    OrgBillingService,
    PaymentMethodNotFound,
    RequestOrigin,
    allowed_origins,
    validate_return_url,
)
from tests.fakes_billing import (
    FakeBillingStore,
    FakeCommitSession,
    FakeStripe,
    org_record,
    subscribed_record,
)

ORIGINS = allowed_origins("https://app.example.com, http://localhost:3000/")
PRICES = {
    (PlanKey.PRO, "monthly"): "price_pro_m",
    (PlanKey.PRO, "yearly"): "price_pro_y",
    (PlanKey.ENTERPRISE, "monthly"): "price_ent_m",
}
OK_URL = "https://app.example.com/billing?x=1"
CHECKOUT: dict[str, Any] = {
    "plan": PlanKey.PRO,
    "interval": "monthly",
    "success_url": OK_URL,
    "cancel_url": OK_URL,
    "request_key": None,
}


def build(
    record: Any = None, role: MembershipRole = MembershipRole.OWNER
) -> tuple[OrgBillingService, FakeStripe, FakeBillingStore, FakeCommitSession]:
    store = FakeBillingStore()
    store.add(record or org_record(), "u1", role)
    stripe = FakeStripe()
    session = FakeCommitSession()
    service = OrgBillingService(store, session, stripe, PRICES, ORIGINS)  # type: ignore[arg-type]
    return service, stripe, store, session


def test_allowed_origins_normalises_the_setting():
    assert ORIGINS == {"https://app.example.com", "http://localhost:3000"}
    assert allowed_origins("") == frozenset()


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/x",
        "https://app.example.com.evil.com/x",
        "https://app.example.com@evil.com/x",
        "https://user:pw@app.example.com/x",
        "http://app.example.com/x",
        "https://app.example.com:8443/x",
        "javascript:alert(1)",
        "//app.example.com/x",
        "/relative",
        "https://app.example.com\\@evil.com",
        "https://app.example.com/a b",
        "https://app.example.com:notaport/x",
        "",
        "https://app.example.com/" + "a" * 2100,
    ],
)
def test_return_url_outside_the_allow_list_is_rejected(url):
    with pytest.raises(InvalidReturnUrl):
        validate_return_url(url, ORIGINS)


def test_return_url_on_the_allow_list_is_accepted_unchanged():
    assert validate_return_url(OK_URL, ORIGINS) == OK_URL
    local = "http://localhost:3000/billing"
    assert validate_return_url(local, ORIGINS) == local


def test_no_configured_origins_rejects_everything():
    with pytest.raises(InvalidReturnUrl):
        validate_return_url(OK_URL, frozenset())


async def test_non_member_gets_not_found():
    service, *_ = build()

    with pytest.raises(OrganizationNotFound):
        await service.summary("org1", "stranger")


async def test_unknown_organisation_gets_not_found():
    service, *_ = build()

    with pytest.raises(OrganizationNotFound):
        await service.summary("missing", "u1")


async def test_organisation_deleted_after_the_role_check_gets_not_found():
    service, _, store, _ = build()

    async def gone(organization_id: str) -> None:
        return None

    store.get = gone  # type: ignore[method-assign]

    with pytest.raises(OrganizationNotFound):
        await service.summary("org1", "u1")


async def test_staff_member_is_forbidden_on_every_operation():
    service, stripe, *_ = build(subscribed_record(), MembershipRole.STAFF)

    for call in (
        service.summary("org1", "u1"),
        service.invoices("org1", "u1"),
        service.payment_methods("org1", "u1"),
        service.set_cancellation("org1", "u1", cancel=True, request_key=None),
        service.change_plan(
            "org1", "u1", plan=PlanKey.PRO, interval="yearly", request_key=None
        ),
        service.open_portal("org1", "u1", return_url=OK_URL, request_key=None),
        service.start_checkout("org1", "u1", **CHECKOUT),
    ):
        with pytest.raises(BillingForbidden):
            await call
    assert stripe.calls == []


@pytest.mark.parametrize("role", [MembershipRole.OWNER, MembershipRole.ADMIN])
async def test_owner_and_admin_can_read_the_summary(role):
    service, *_ = build(subscribed_record(), role)

    summary = await service.summary("org1", "u1")

    assert summary.plan.key == PlanKey.PRO
    assert summary.plan.max_stores == 3
    assert (summary.status, summary.has_billing_account, summary.has_subscription) == (
        "active",
        True,
        True,
    )


async def test_unknown_stored_tier_reads_as_free():
    service, *_ = build(org_record(subscription_tier="legacy"))

    assert (await service.summary("org1", "u1")).plan.key == PlanKey.FREE


async def test_checkout_creates_and_saves_the_customer_before_the_session():
    service, stripe, store, session = build()

    url = await service.start_checkout(
        "org1",
        "u1",
        **{**CHECKOUT, "interval": "yearly", "request_key": "client-key-1"},
    )

    assert url == "https://checkout.stripe.test/session"
    assert stripe.names() == ["create_customer", "create_checkout_session"]
    assert store.orgs["org1"].stripe_customer_id == "cus_new"
    assert session.commits == 2  # customer link, then the audit row
    sent = stripe.last("create_checkout_session")
    assert sent["customer_id"] == "cus_new"
    assert sent["price_id"] == "price_pro_y"
    assert sent["idempotency_key"] == "sc-checkout-org1-client-key-1"
    assert stripe.last("create_customer")["idempotency_key"] == "sc-customer-org1"


async def test_checkout_reuses_an_existing_customer():
    service, stripe, _, session = build(org_record(stripe_customer_id="cus_old"))

    await service.start_checkout(
        "org1", "u1", **{**CHECKOUT, "plan": PlanKey.ENTERPRISE}
    )

    assert stripe.names() == ["create_checkout_session"]
    assert stripe.last("create_checkout_session")["customer_id"] == "cus_old"
    assert session.commits == 1  # only the audit row


async def test_checkout_without_client_key_generates_distinct_keys():
    service, stripe, *_ = build(org_record(stripe_customer_id="cus_old"))

    await service.start_checkout("org1", "u1", **CHECKOUT)
    await service.start_checkout("org1", "u1", **CHECKOUT)

    keys = [args["idempotency_key"] for _, args in stripe.calls]
    assert keys[0] != keys[1]


@pytest.mark.parametrize("bad", ["success_url", "cancel_url"])
async def test_checkout_rejects_a_return_url_off_the_allow_list(bad):
    service, stripe, *_ = build()

    with pytest.raises(InvalidReturnUrl):
        await service.start_checkout(
            "org1", "u1", **{**CHECKOUT, bad: "https://evil.test/"}
        )
    assert stripe.calls == []


async def test_checkout_refused_when_a_subscription_is_already_live():
    service, stripe, *_ = build(subscribed_record())

    with pytest.raises(BillingConflict):
        await service.start_checkout("org1", "u1", **CHECKOUT)
    assert stripe.calls == []


async def test_checkout_allowed_again_after_the_subscription_ended():
    service, stripe, *_ = build(subscribed_record(subscription_status="canceled"))

    await service.start_checkout("org1", "u1", **CHECKOUT)

    assert "create_checkout_session" in stripe.names()


async def test_checkout_for_the_free_plan_is_refused():
    service, *_ = build()

    with pytest.raises(BillingConflict):
        await service.start_checkout("org1", "u1", **{**CHECKOUT, "plan": PlanKey.FREE})


async def test_checkout_is_unavailable_when_the_price_is_not_configured():
    service, stripe, *_ = build()

    with pytest.raises(BillingNotConfigured):
        await service.start_checkout(
            "org1",
            "u1",
            **{**CHECKOUT, "plan": PlanKey.ENTERPRISE, "interval": "yearly"},
        )
    assert stripe.calls == []


async def test_stripe_failure_becomes_billing_unavailable():
    service, stripe, *_ = build()
    stripe.fail = True

    with pytest.raises(BillingUnavailable):
        await service.start_checkout("org1", "u1", **CHECKOUT)


async def test_portal_needs_a_billing_account():
    service, stripe, *_ = build()

    with pytest.raises(BillingConflict):
        await service.open_portal("org1", "u1", return_url=OK_URL, request_key=None)
    assert stripe.calls == []


async def test_portal_session_uses_the_organisations_own_customer():
    service, stripe, *_ = build(subscribed_record())

    url = await service.open_portal(
        "org1", "u1", return_url=OK_URL, request_key="abcdefgh"
    )

    assert url == "https://portal.stripe.test/session"
    sent = stripe.last("create_portal_session")
    assert sent["customer_id"] == "cus_1"
    assert sent["return_url"] == OK_URL
    assert sent["idempotency_key"] == "sc-portal-org1-abcdefgh"


async def test_portal_rejects_a_foreign_return_url():
    service, stripe, *_ = build(subscribed_record())

    with pytest.raises(InvalidReturnUrl):
        await service.open_portal(
            "org1", "u1", return_url="https://evil.test/", request_key=None
        )
    assert stripe.calls == []


async def test_change_plan_swaps_the_price_on_the_existing_item():
    service, stripe, *_ = build(subscribed_record())

    await service.change_plan(
        "org1", "u1", plan=PlanKey.PRO, interval="yearly", request_key="abcdefgh"
    )

    sent = stripe.last("change_subscription_price")
    assert sent["subscription_id"] == "sub_1"
    assert sent["item_id"] == "si_1"
    assert sent["price_id"] == "price_pro_y"
    assert sent["idempotency_key"] == "sc-change-org1-abcdefgh"


async def test_change_plan_to_the_current_price_is_refused():
    service, stripe, *_ = build(subscribed_record())

    with pytest.raises(BillingConflict):
        await service.change_plan(
            "org1", "u1", plan=PlanKey.PRO, interval="monthly", request_key=None
        )
    assert "change_subscription_price" not in stripe.names()


async def test_change_plan_refuses_a_subscription_of_another_customer():
    service, stripe, *_ = build(subscribed_record())
    stripe.subscription = replace(stripe.subscription, customer_id="cus_other")

    with pytest.raises(BillingConflict):
        await service.change_plan(
            "org1", "u1", plan=PlanKey.PRO, interval="yearly", request_key=None
        )
    assert "change_subscription_price" not in stripe.names()


async def test_change_plan_without_a_live_subscription_is_refused():
    service, *_ = build(org_record(stripe_customer_id="cus_1"))

    with pytest.raises(BillingConflict):
        await service.change_plan(
            "org1", "u1", plan=PlanKey.PRO, interval="yearly", request_key=None
        )


async def test_change_plan_to_free_is_refused():
    service, *_ = build(subscribed_record())

    with pytest.raises(BillingConflict):
        await service.change_plan(
            "org1", "u1", plan=PlanKey.FREE, interval="yearly", request_key=None
        )


@pytest.mark.parametrize("cancel", [True, False])
async def test_cancel_and_resume_toggle_cancel_at_period_end(cancel):
    service, stripe, *_ = build(subscribed_record())

    await service.set_cancellation("org1", "u1", cancel=cancel, request_key="abcdefgh")

    sent = stripe.last("set_cancel_at_period_end")
    assert sent["subscription_id"] == "sub_1"
    assert sent["cancel"] is cancel
    word = "cancel" if cancel else "resume"
    assert sent["idempotency_key"] == f"sc-{word}-org1-abcdefgh"


async def test_cancel_without_a_subscription_is_refused():
    service, *_ = build()

    with pytest.raises(BillingConflict):
        await service.set_cancellation("org1", "u1", cancel=True, request_key=None)


async def test_invoices_and_payment_methods_come_from_the_organisations_customer():
    service, stripe, *_ = build(subscribed_record())

    invoices = await service.invoices("org1", "u1")
    methods = await service.payment_methods("org1", "u1")

    assert [i.id for i in invoices] == ["in_1"]
    assert [m.last4 for m in methods] == ["4242"]
    assert stripe.last("list_invoices") == {"customer_id": "cus_1"}
    assert stripe.last("list_payment_methods") == {"customer_id": "cus_1"}


async def test_invoices_and_payment_methods_are_empty_without_a_customer():
    service, stripe, *_ = build()

    assert await service.invoices("org1", "u1") == []
    assert await service.payment_methods("org1", "u1") == []
    assert stripe.calls == []


@pytest.mark.parametrize("status", ["unpaid", "incomplete", "paused"])
async def test_checkout_refused_for_every_status_that_still_has_a_subscription(status):
    service, stripe, *_ = build(subscribed_record(subscription_status=status))

    with pytest.raises(BillingConflict):
        await service.start_checkout("org1", "u1", **CHECKOUT)
    assert stripe.calls == []


async def test_read_transaction_is_ended_before_stripe_is_called():
    service, _, _, session = build(subscribed_record())

    await service.invoices("org1", "u1")

    assert session.rollbacks == 1


async def test_summary_reports_cancel_at_period_end_and_interval():
    service, *_ = build(
        subscribed_record(
            stripe_cancel_at_period_end=True, stripe_price_id="price_pro_y"
        )
    )

    summary = await service.summary("org1", "u1")

    assert summary.cancel_at_period_end is True
    assert summary.interval == "yearly"


@pytest.mark.parametrize("price", [None, "price_rotated_away"])
async def test_interval_is_null_when_the_price_is_not_in_the_catalogue(price):
    service, *_ = build(subscribed_record(stripe_price_id=price))

    assert (await service.summary("org1", "u1")).interval is None


async def test_payment_methods_flag_the_customers_default_card():
    service, stripe, *_ = build(subscribed_record())
    stripe.payment_methods = [
        replace(stripe.payment_methods[0], id="pm_a"),
        replace(stripe.payment_methods[0], id="pm_b"),
    ]
    stripe.default_payment_method = "pm_b"

    methods = await service.payment_methods("org1", "u1")

    assert [(m.id, m.is_default) for m in methods] == [("pm_a", False), ("pm_b", True)]


async def test_delete_payment_method_of_another_customer_is_not_found():
    service, stripe, *_ = build(subscribed_record())

    with pytest.raises(PaymentMethodNotFound):
        await service.delete_payment_method(
            "org1", "u1", "pm_other", request_key="key-00001"
        )
    assert "detach_payment_method" not in stripe.names()


async def test_payment_method_without_a_billing_account_is_not_found():
    service, stripe, *_ = build()

    with pytest.raises(PaymentMethodNotFound):
        await service.set_default_payment_method(
            "org1", "u1", "pm_1", request_key="key-00001"
        )
    assert stripe.calls == []


async def test_default_card_can_be_deleted_without_a_live_subscription():
    service, stripe, *_ = build(subscribed_record(subscription_status="canceled"))

    await service.delete_payment_method("org1", "u1", "pm_1", request_key="key-00001")

    assert stripe.last("detach_payment_method")["payment_method_id"] == "pm_1"


async def test_stripe_failure_while_checking_ownership_is_unavailable():
    service, stripe, *_ = build(subscribed_record())
    stripe.fail = True

    with pytest.raises(BillingUnavailable):
        await service.delete_payment_method(
            "org1", "u1", "pm_1", request_key="key-00001"
        )


async def test_accepted_changes_each_stage_one_audit_row_without_secrets():
    service, _, _, session = build(subscribed_record())

    await service.change_plan(
        "org1", "u1", plan=PlanKey.PRO, interval="yearly", request_key=None
    )
    await service.set_cancellation("org1", "u1", cancel=True, request_key=None)

    assert [row.action for row in session.added] == [
        "billing.change_plan",
        "billing.cancel",
    ]
    assert all(
        (row.user_id, row.organization_id, row.store_id) == ("u1", "org1", None)
        for row in session.added
    )
    assert "cus_1" not in str([row.metadata_ for row in session.added])


async def test_refused_or_failed_change_stages_no_audit_row():
    service, stripe, _, session = build(subscribed_record())
    stripe.fail = True

    with pytest.raises(BillingUnavailable):
        await service.set_cancellation("org1", "u1", cancel=True, request_key=None)
    with pytest.raises(BillingConflict):
        await service.change_plan(
            "org1", "u1", plan=PlanKey.FREE, interval="monthly", request_key=None
        )

    assert session.added == []


class FailingAuditSession(FakeCommitSession):
    """A session whose commit fails, like a database outage after Stripe accepted."""

    async def commit(self) -> None:
        raise RuntimeError("database unavailable")


async def test_audit_failure_after_stripe_accepts_is_logged_and_not_raised(caplog):
    service, stripe, store, _ = build(subscribed_record())
    session = FailingAuditSession()
    service = OrgBillingService(store, session, stripe, PRICES, ORIGINS)  # type: ignore[arg-type]

    with caplog.at_level("ERROR", logger="app.services.org_billing"):
        await service.set_cancellation(
            "org1", "u1", cancel=True, request_key="client-key-1"
        )

    record = caplog.records[-1]
    assert session.rollbacks >= 2  # authorize, then the failed audit write
    assert record.organization_id == "org1"  # type: ignore[attr-defined]
    assert record.audit_action == "billing.cancel"  # type: ignore[attr-defined]
    assert record.idempotency_key == "sc-cancel-org1-client-key-1"  # type: ignore[attr-defined]


async def test_billing_audit_row_carries_request_context():
    store = FakeBillingStore()
    store.add(subscribed_record(), "u1", MembershipRole.OWNER)
    session = FakeCommitSession()
    origin = RequestOrigin("203.0.113.9", "pytestagent", "req-7")
    service = OrgBillingService(store, session, FakeStripe(), PRICES, ORIGINS, origin)  # type: ignore[arg-type]

    await service.set_cancellation("org1", "u1", cancel=True, request_key=None)

    row = session.added[0]
    assert (row.ip_address, row.user_agent) == ("203.0.113.9", "pytestagent")
    assert row.metadata_ == {"request_id": "req-7"}
