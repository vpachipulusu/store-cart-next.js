"""Stripe Connect client (KAN-67): create a connected account, its hosted onboarding link, read its state.

Reuses the Stripe Billing transport (``HttpStripeBilling._call``), so the same timeout,
error mapping and no-secret logging apply: every failure becomes a ``StripeError``
without Stripe text. Tests inject a fake ``StripeConnect``.
"""

from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings
from app.core.stripe_billing import (
    HttpStripeBilling,
    StripeNotConfigured,
    as_dict,
    require_text,
)


@dataclass(frozen=True)
class StripeAccountState:
    """The capability flags of a connected account, as Stripe reports them now."""

    charges_enabled: bool
    payouts_enabled: bool
    details_submitted: bool


class StripeConnect(Protocol):
    async def get_account(self, account_id: str) -> StripeAccountState: ...

    async def create_account(
        self, *, organization_id: str, idempotency_key: str
    ) -> str: ...

    async def create_account_link(
        self,
        *,
        account_id: str,
        refresh_url: str,
        return_url: str,
        idempotency_key: str,
    ) -> str: ...


class HttpStripeConnect(HttpStripeBilling):
    async def get_account(self, account_id: str) -> StripeAccountState:
        body = as_dict(await self._call("GET", f"/accounts/{account_id}"))
        return StripeAccountState(
            charges_enabled=body.get("charges_enabled") is True,
            payouts_enabled=body.get("payouts_enabled") is True,
            details_submitted=body.get("details_submitted") is True,
        )

    async def create_account(
        self, *, organization_id: str, idempotency_key: str
    ) -> str:
        body = await self._call(
            "POST",
            "/accounts",
            data={
                "type": "express",
                "capabilities[card_payments][requested]": "true",
                "capabilities[transfers][requested]": "true",
                "metadata[organization_id]": organization_id,
            },
            idempotency_key=idempotency_key,
        )
        return require_text(body.get("id"))

    async def create_account_link(
        self,
        *,
        account_id: str,
        refresh_url: str,
        return_url: str,
        idempotency_key: str,
    ) -> str:
        body = await self._call(
            "POST",
            "/account_links",
            data={
                "account": account_id,
                "type": "account_onboarding",
                "refresh_url": refresh_url,
                "return_url": return_url,
            },
            idempotency_key=idempotency_key,
        )
        return require_text(body.get("url"))


LIVE_KEY_PREFIXES = ("sk_live_", "rk_live_")


def stripe_livemode() -> bool:
    """Whether the platform key is a live key; Connect events of the other mode are ignored."""
    secret = settings.STRIPE_SECRET_KEY
    return secret is not None and secret.get_secret_value().startswith(
        LIVE_KEY_PREFIXES
    )


def get_stripe_connect() -> StripeConnect:
    """The one place the real client is built; tests override the dependency that calls it."""
    secret = settings.STRIPE_SECRET_KEY
    if secret is None or not secret.get_secret_value():
        raise StripeNotConfigured("STRIPE_SECRET_KEY is not set")
    return HttpStripeConnect(secret.get_secret_value())
