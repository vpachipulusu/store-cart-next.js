"""Test doubles for organisation billing (KAN-43): a recording Stripe client and an in-memory store."""

from dataclasses import replace
from typing import Any

from app.core.stripe_billing import (
    StripeError,
    StripeInvoice,
    StripeNotFound,
    StripePaymentMethod,
    StripeSubscription,
)
from app.models.platform.membership import MembershipRole
from app.repositories.org_billing import OrgBillingRecord


class FakeStripe:
    """Implements StripeBilling; records every call and can be told to fail."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = False
        self.subscription = StripeSubscription("sub_1", "cus_1", "si_1", "price_pro_m")
        self.invoices = [
            StripeInvoice(
                "in_1", "A-0001", "paid", 1000, 1000, "gbp", 1_800_000_000, None, None
            )
        ]
        self.payment_methods = [StripePaymentMethod("pm_1", "visa", "4242", 12, 2030)]
        self.default_payment_method: str | None = "pm_1"
        # payment method id -> owning customer id; unknown ids raise StripeNotFound
        self.payment_method_owners: dict[str, str | None] = {
            "pm_1": "cus_1",
            "pm_other": "cus_other",
        }

    def _record(self, call: str, /, **kwargs: Any) -> None:
        self.calls.append((call, kwargs))
        if self.fail:
            raise StripeError("Stripe request failed")

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def last(self, name: str) -> dict[str, Any]:
        return next(args for call, args in reversed(self.calls) if call == name)

    async def create_customer(self, **kwargs: Any) -> str:
        self._record("create_customer", **kwargs)
        return "cus_new"

    async def create_checkout_session(self, **kwargs: Any) -> str:
        self._record("create_checkout_session", **kwargs)
        return "https://checkout.stripe.test/session"

    async def create_portal_session(self, **kwargs: Any) -> str:
        self._record("create_portal_session", **kwargs)
        return "https://portal.stripe.test/session"

    async def get_subscription(self, subscription_id: str) -> StripeSubscription:
        self._record("get_subscription", subscription_id=subscription_id)
        return self.subscription

    async def change_subscription_price(self, **kwargs: Any) -> None:
        self._record("change_subscription_price", **kwargs)

    async def set_cancel_at_period_end(self, **kwargs: Any) -> None:
        self._record("set_cancel_at_period_end", **kwargs)

    async def list_invoices(self, customer_id: str) -> list[StripeInvoice]:
        self._record("list_invoices", customer_id=customer_id)
        return self.invoices

    async def list_payment_methods(self, customer_id: str) -> list[StripePaymentMethod]:
        self._record("list_payment_methods", customer_id=customer_id)
        return self.payment_methods

    async def get_default_payment_method_id(self, customer_id: str) -> str | None:
        self._record("get_default_payment_method_id", customer_id=customer_id)
        return self.default_payment_method

    async def get_payment_method_customer_id(
        self, payment_method_id: str
    ) -> str | None:
        self._record(
            "get_payment_method_customer_id", payment_method_id=payment_method_id
        )
        if payment_method_id not in self.payment_method_owners:
            raise StripeNotFound("Stripe request failed")
        return self.payment_method_owners[payment_method_id]

    async def detach_payment_method(self, **kwargs: Any) -> None:
        self._record("detach_payment_method", **kwargs)

    async def set_default_payment_method(self, **kwargs: Any) -> None:
        self._record("set_default_payment_method", **kwargs)


class FakeBillingStore:
    """Implements BillingStore in memory."""

    def __init__(self) -> None:
        self.roles: dict[tuple[str, str], MembershipRole] = {}
        self.orgs: dict[str, OrgBillingRecord] = {}

    def add(self, record: OrgBillingRecord, user_id: str, role: MembershipRole) -> None:
        self.orgs[record.id] = record
        self.roles[(record.id, user_id)] = role

    async def get_role(
        self, organization_id: str, user_id: str
    ) -> MembershipRole | None:
        return self.roles.get((organization_id, user_id))

    async def get(self, organization_id: str) -> OrgBillingRecord | None:
        return self.orgs.get(organization_id)

    async def link_customer(self, organization_id: str, customer_id: str) -> str:
        record = self.orgs[organization_id]
        if record.stripe_customer_id is None:
            record = replace(record, stripe_customer_id=customer_id)
            self.orgs[organization_id] = record
        return record.stripe_customer_id or customer_id


class FakeCommitSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def commit(self) -> None:
        self.commits += 1


def org_record(**overrides: Any) -> OrgBillingRecord:
    base = OrgBillingRecord(
        id="org1",
        name="Acme",
        stripe_customer_id=None,
        stripe_subscription_id=None,
        stripe_price_id=None,
        stripe_current_period_end=None,
        subscription_tier="free",
        subscription_status="inactive",
    )
    return replace(base, **overrides)


def subscribed_record(**overrides: Any) -> OrgBillingRecord:
    fields: dict[str, Any] = {
        "stripe_customer_id": "cus_1",
        "stripe_subscription_id": "sub_1",
        "stripe_price_id": "price_pro_m",
        "subscription_tier": "pro",
        "subscription_status": "active",
    }
    return org_record(**{**fields, **overrides})
