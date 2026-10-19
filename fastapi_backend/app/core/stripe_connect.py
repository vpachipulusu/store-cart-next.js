"""Stripe Connect client (KAN-67): create a connected account and its hosted onboarding link.

Reuses the Stripe Billing transport (``HttpStripeBilling._call``), so the same timeout,
error mapping and no-secret logging apply: every failure becomes a ``StripeError``
without Stripe text. Tests inject a fake ``StripeConnect``.
"""

from typing import Protocol

from app.core.config import settings
from app.core.stripe_billing import (
    HttpStripeBilling,
    StripeNotConfigured,
    require_text,
)


class StripeConnect(Protocol):
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


def get_stripe_connect() -> StripeConnect:
    """The one place the real client is built; tests override this dependency."""
    secret = settings.STRIPE_SECRET_KEY
    if secret is None or not secret.get_secret_value():
        raise StripeNotConfigured("STRIPE_SECRET_KEY is not set")
    return HttpStripeConnect(secret.get_secret_value())
