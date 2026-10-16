"""Read-only Stripe price lookup for the public plan-price route (KAN-208)."""

import re
from typing import Protocol

from app.core.config import settings
from app.core.stripe_billing import HttpStripeBilling

# Ids come from configuration, never from a request; the check keeps a bad value from
# changing the Stripe path.
PRICE_ID = re.compile(r"price_[A-Za-z0-9]{1,64}")


class StripePriceReader(Protocol):
    async def get_unit_amount(self, price_id: str) -> int | None: ...


class HttpStripePrices(HttpStripeBilling):
    async def get_unit_amount(self, price_id: str) -> int | None:
        """The price's ``unit_amount`` in minor units, or None when it has none."""
        if not PRICE_ID.fullmatch(price_id):
            return None
        body = await self._call("GET", f"/prices/{price_id}")
        amount = body.get("unit_amount")
        return amount if type(amount) is int and amount >= 0 else None


def get_stripe_prices() -> StripePriceReader | None:
    """The one place the real client is built; None when Stripe is not configured."""
    secret = settings.STRIPE_SECRET_KEY
    if secret is None or not secret.get_secret_value():
        return None
    return HttpStripePrices(secret.get_secret_value())
