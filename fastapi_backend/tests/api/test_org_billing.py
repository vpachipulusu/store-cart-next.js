"""Organisation billing routes with fakes behind the real router, dependencies and error mapping."""

import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

import pytest
from fastapi import Header, HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.auth import get_current_identity
from app.api.deps import get_session
from app.api.me import get_current_user_id
from app.api.v1.org_billing import (
    get_org_billing_service,
    price_catalogue,
)
from app.core.config import settings
from app.core.firebase import VerifiedIdentity
from app.core.plans import PlanKey
from app.main import create_app
from app.models.platform.membership import MembershipRole
from app.services.org_billing import OrgBillingService, allowed_origins
from tests.fakes_billing import (
    FakeBillingStore,
    FakeCommitSession,
    FakeStripe,
    org_record,
    subscribed_record,
)

KEY = "test-only-internal-service-key-not-for-deployment"
OK_URL = "https://app.example.com/billing"
BASE = "/v1/organizations/org1/billing"
PRICES = {
    (PlanKey.PRO, "monthly"): "price_pro_m",
    (PlanKey.PRO, "yearly"): "price_pro_y",
}


def identity() -> VerifiedIdentity:
    return VerifiedIdentity("fb-test", "test@example.com", True, 0)


class Harness:
    def __init__(self) -> None:
        self.store = FakeBillingStore()
        self.stripe = FakeStripe()
        self.session = FakeCommitSession()
        self.store.add(subscribed_record(), "owner", MembershipRole.OWNER)
        self.store.roles[("org1", "admin")] = MembershipRole.ADMIN
        self.store.roles[("org1", "staff")] = MembershipRole.STAFF
        self.store.add(
            org_record(id="org2", name="Other"), "other-owner", MembershipRole.OWNER
        )
        self.app = create_app()

        async def current_user(
            x_test_user: Annotated[str | None, Header()] = None,
        ) -> str:
            if x_test_user is None:
                raise HTTPException(401, "Invalid authentication")
            return x_test_user

        def service() -> OrgBillingService:
            return OrgBillingService(
                self.store,  # type: ignore[arg-type]
                self.session,  # type: ignore[arg-type]
                self.stripe,
                PRICES,
                allowed_origins("https://app.example.com"),
            )

        self.app.dependency_overrides[get_current_user_id] = current_user
        self.app.dependency_overrides[get_current_identity] = identity
        self.app.dependency_overrides[get_org_billing_service] = service


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    yield Harness()


def client(harness: Harness, user: str | None = "owner") -> AsyncClient:
    headers = {"X-Internal-Key": KEY}
    if user:
        headers["X-Test-User"] = user
    return AsyncClient(
        transport=ASGITransport(app=harness.app, raise_app_exceptions=False),
        base_url="http://test",
        headers=headers,
    )


CHECKOUT_BODY: dict[str, Any] = {
    "plan": "pro",
    "interval": "yearly",
    "success_url": OK_URL,
    "cancel_url": OK_URL,
}


async def test_missing_internal_key_is_401(harness):
    async with client(harness) as http:
        http.headers.pop("X-Internal-Key")
        result = await http.get(BASE)

    assert result.status_code == 401


async def test_missing_session_is_401(harness):
    async with client(harness, user=None) as http:
        result = await http.get(BASE)

    assert result.status_code == 401
    assert harness.stripe.calls == []


async def test_summary_returns_plan_limits_from_the_catalogue(harness):
    async with client(harness) as http:
        result = await http.get(BASE)

    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    data = result.json()["data"]
    assert data["plan"] == {
        "key": "pro",
        "name": "Pro",
        "max_stores": 3,
        "max_products": 1000,
        "max_staff": 5,
    }
    assert data["subscription_status"] == "active"
    assert data["has_subscription"] is True
    assert data["cancel_at_period_end"] is False
    assert data["interval"] == "monthly"
    assert "cus_1" not in str(data)
    assert "sub_1" not in str(data)


async def test_admin_may_read_but_staff_and_strangers_may_not(harness):
    async with client(harness, "admin") as http:
        assert (await http.get(BASE)).status_code == 200
    async with client(harness, "staff") as http:
        staff = await http.get(BASE)
    async with client(harness, "nobody") as http:
        stranger = await http.get(BASE)

    assert (staff.status_code, staff.json()) == (
        403,
        {"success": False, "error": "Forbidden"},
    )
    assert stranger.status_code == 404


async def test_another_organisations_owner_cannot_touch_this_one(harness):
    async with client(harness, "other-owner") as http:
        results = [
            await http.get(BASE),
            await http.get(f"{BASE}/invoices"),
            await http.get(f"{BASE}/payment-methods"),
            await http.post(f"{BASE}/cancel"),
            await http.post(f"{BASE}/portal", json={"return_url": OK_URL}),
        ]

    assert [r.status_code for r in results] == [404] * 5
    assert harness.stripe.calls == []


async def test_checkout_returns_the_session_url_with_the_idempotency_key(harness):
    harness.store.orgs["org1"] = org_record(stripe_customer_id="cus_1")

    async with client(harness) as http:
        result = await http.post(
            f"{BASE}/checkout",
            json=CHECKOUT_BODY,
            headers={"Idempotency-Key": "client-key-1"},
        )

    assert result.status_code == 200
    assert result.json()["data"] == {"url": "https://checkout.stripe.test/session"}
    sent = harness.stripe.last("create_checkout_session")
    assert sent["idempotency_key"] == "sc-checkout-org1-client-key-1"
    assert sent["price_id"] == "price_pro_y"


@pytest.mark.parametrize(
    "url", ["https://evil.example.com/", "javascript:alert(1)", "//evil.test/x"]
)
async def test_checkout_with_a_foreign_return_url_is_422(harness, url):
    harness.store.orgs["org1"] = org_record(stripe_customer_id="cus_1")

    async with client(harness) as http:
        result = await http.post(
            f"{BASE}/checkout", json={**CHECKOUT_BODY, "success_url": url}
        )

    assert (result.status_code, result.json()["error"]) == (422, "Invalid return URL")
    assert harness.stripe.calls == []


async def test_checkout_for_an_organisation_already_subscribed_is_409(harness):
    async with client(harness) as http:
        result = await http.post(f"{BASE}/checkout", json=CHECKOUT_BODY)

    assert result.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {**CHECKOUT_BODY, "plan": "free"},
        {**CHECKOUT_BODY, "interval": "weekly"},
        {**CHECKOUT_BODY, "extra": 1},
        {"plan": "pro"},
    ],
)
async def test_checkout_rejects_invalid_bodies(harness, body):
    async with client(harness) as http:
        result = await http.post(f"{BASE}/checkout", json=body)

    assert result.status_code == 422


@pytest.mark.parametrize("key", ["short", "has space here", "x" * 65])
async def test_invalid_idempotency_key_is_422(harness, key):
    async with client(harness) as http:
        result = await http.post(f"{BASE}/cancel", headers={"Idempotency-Key": key})

    assert result.status_code == 422


async def test_stripe_failure_is_a_generic_502(harness):
    harness.stripe.fail = True

    async with client(harness) as http:
        result = await http.post(f"{BASE}/portal", json={"return_url": OK_URL})

    assert result.status_code == 502
    assert result.json() == {"success": False, "error": "Billing provider unavailable"}


async def test_portal_returns_the_session_url(harness):
    async with client(harness) as http:
        result = await http.post(f"{BASE}/portal", json={"return_url": OK_URL})

    assert result.status_code == 200
    assert result.json()["data"]["url"] == "https://portal.stripe.test/session"


async def test_plan_change_cancel_and_resume_return_ok(harness):
    async with client(harness) as http:
        change = await http.post(
            f"{BASE}/plan", json={"plan": "pro", "interval": "yearly"}
        )
        cancel = await http.post(f"{BASE}/cancel")
        resume = await http.post(f"{BASE}/resume")

    assert [r.json() for r in (change, cancel, resume)] == [{"success": True}] * 3
    flags = [
        args["cancel"]
        for name, args in harness.stripe.calls
        if name == "set_cancel_at_period_end"
    ]
    assert flags == [True, False]


async def test_plan_change_to_the_same_price_is_409(harness):
    async with client(harness) as http:
        result = await http.post(
            f"{BASE}/plan", json={"plan": "pro", "interval": "monthly"}
        )

    assert result.status_code == 409


async def test_invoices_and_payment_methods_expose_only_the_summary_fields(harness):
    async with client(harness) as http:
        invoices = await http.get(f"{BASE}/invoices")
        methods = await http.get(f"{BASE}/payment-methods")

    assert invoices.json()["data"][0]["number"] == "A-0001"
    assert methods.json()["data"] == [
        {
            "id": "pm_1",
            "brand": "visa",
            "last4": "4242",
            "exp_month": 12,
            "exp_year": 2030,
            "is_default": True,
        }
    ]


async def test_malformed_organisation_id_is_422(harness):
    async with client(harness) as http:
        result = await http.get("/v1/organizations/bad%20id/billing")

    assert result.status_code == 422


async def test_unconfigured_secret_key_is_503(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", None)
    app = create_app()

    async def user() -> str:
        return "owner"

    async def no_session() -> AsyncIterator[FakeCommitSession]:
        yield FakeCommitSession()

    app.dependency_overrides[get_current_user_id] = user
    app.dependency_overrides[get_current_identity] = identity
    app.dependency_overrides[get_session] = no_session  # type: ignore[assignment]
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-Internal-Key": KEY}
    ) as http:
        result = await http.get(BASE)

    assert result.status_code == 503
    assert result.json() == {
        "success": False,
        "error": "Service temporarily unavailable",
    }


def test_price_catalogue_reads_settings(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID_PRO_MONTHLY", "price_a")
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID_PRO_YEARLY", None)
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID_ENTERPRISE_MONTHLY", "price_b")
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID_ENTERPRISE_YEARLY", None)

    assert price_catalogue() == {
        (PlanKey.PRO, "monthly"): "price_a",
        (PlanKey.ENTERPRISE, "monthly"): "price_b",
    }


PM = f"{BASE}/payment-methods"
IDEMPOTENT = {"Idempotency-Key": "pm-key-0001"}


async def test_delete_payment_method_detaches_it_with_the_client_key(harness):
    harness.stripe.default_payment_method = "pm_other_default"
    harness.stripe.payment_method_owners["pm_2"] = "cus_1"
    async with client(harness) as http:
        result = await http.delete(f"{PM}/pm_2", headers=IDEMPOTENT)

    assert result.status_code == 200
    assert result.json() == {"success": True}
    assert harness.stripe.last("detach_payment_method") == {
        "payment_method_id": "pm_2",
        "idempotency_key": "sc-pm-delete-org1-pm-key-0001",
    }


async def test_set_default_payment_method_updates_the_customer(harness):
    async with client(harness, "admin") as http:
        result = await http.post(f"{PM}/pm_1/default", headers=IDEMPOTENT)

    assert result.status_code == 200
    assert harness.stripe.last("set_default_payment_method") == {
        "customer_id": "cus_1",
        "payment_method_id": "pm_1",
        "idempotency_key": "sc-pm-default-org1-pm-key-0001",
    }


async def test_payment_method_changes_need_an_idempotency_key(harness):
    async with client(harness) as http:
        deleted = await http.delete(f"{PM}/pm_1")
        default = await http.post(f"{PM}/pm_1/default")

    assert (deleted.status_code, default.status_code) == (422, 422)
    assert harness.stripe.calls == []


async def test_foreign_and_unknown_payment_methods_get_the_same_404(harness):
    async with client(harness) as http:
        foreign = await http.delete(f"{PM}/pm_other", headers=IDEMPOTENT)
        unknown = await http.delete(f"{PM}/pm_nope", headers=IDEMPOTENT)
        foreign_default = await http.post(f"{PM}/pm_other/default", headers=IDEMPOTENT)

    assert foreign.status_code == unknown.status_code == 404
    assert foreign.content == unknown.content
    assert foreign_default.status_code == 404
    assert "detach_payment_method" not in harness.stripe.names()
    assert "set_default_payment_method" not in harness.stripe.names()


async def test_deleting_the_default_card_of_a_live_subscription_is_409(harness):
    async with client(harness) as http:
        result = await http.delete(f"{PM}/pm_1", headers=IDEMPOTENT)

    assert result.status_code == 409
    assert "detach_payment_method" not in harness.stripe.names()


async def test_payment_method_changes_are_owner_or_admin_only(harness):
    async with client(harness, "staff") as staff:
        a = await staff.delete(f"{PM}/pm_1", headers=IDEMPOTENT)
        b = await staff.post(f"{PM}/pm_1/default", headers=IDEMPOTENT)
    async with client(harness, "other-owner") as stranger:
        c = await stranger.delete(f"{PM}/pm_1", headers=IDEMPOTENT)

    assert (a.status_code, b.status_code, c.status_code) == (403, 403, 404)
    assert harness.stripe.calls == []


async def test_malformed_payment_method_id_is_422(harness):
    async with client(harness) as http:
        result = await http.delete(f"{PM}/not-a-pm", headers=IDEMPOTENT)

    assert result.status_code == 422


def billing_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.api.v1.org_billing"]


async def test_expected_checkout_rejections_log_cause_and_status_at_info(
    harness, caplog
):
    harness.store.orgs["org1"] = org_record(stripe_customer_id="cus_1")

    with caplog.at_level(logging.INFO, logger="app.api.v1.org_billing"):
        async with client(harness) as http:
            result = await http.post(
                f"{BASE}/checkout",
                json={**CHECKOUT_BODY, "success_url": "https://evil.example.com/x"},
            )

    assert result.status_code == 422
    (record,) = billing_records(caplog)
    assert record.levelno == logging.INFO
    assert record.getMessage() == (
        "org billing request failed: cause=InvalidReturnUrl status=422"
    )
    assert "cus_1" not in caplog.text


async def test_stripe_failure_logs_cause_and_status_at_warning(harness, caplog):
    harness.store.orgs["org1"] = org_record(stripe_customer_id="cus_1")
    harness.stripe.fail = True

    with caplog.at_level(logging.INFO, logger="app.api.v1.org_billing"):
        async with client(harness) as http:
            result = await http.post(f"{BASE}/checkout", json=CHECKOUT_BODY)

    assert result.status_code == 502
    (record,) = billing_records(caplog)
    assert record.levelno == logging.WARNING
    assert record.getMessage() == (
        "org billing request failed: cause=BillingUnavailable status=502"
    )
    assert "cus_1" not in caplog.text
