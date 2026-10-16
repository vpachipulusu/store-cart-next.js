"""Plan prices from the Stripe catalogue (KAN-208).

Replaces the frontend's direct ``stripe.prices.retrieve`` calls. A price that is not
configured or cannot be read is ``None`` so the caller can fall back to its own default;
one bad price never hides the others.
"""

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass

from app.core.stripe_billing import StripeError
from app.core.stripe_prices import StripePriceReader

logger = logging.getLogger("storecart.plan_prices")

PriceKey = tuple[str, str]  # (tier, interval)


@dataclass(frozen=True)
class TierPrices:
    monthly: int | None
    yearly: int | None


@dataclass(frozen=True)
class PlanPrices:
    pro: TierPrices
    enterprise: TierPrices


class PlanPricesService:
    def __init__(
        self, reader: StripePriceReader | None, price_ids: Mapping[PriceKey, str]
    ) -> None:
        self._reader = reader
        self._price_ids = price_ids

    async def _amount(self, key: PriceKey) -> int | None:
        price_id = self._price_ids.get(key)
        if self._reader is None or not price_id:
            return None
        try:
            return await self._reader.get_unit_amount(price_id)
        except StripeError:
            logger.warning("plan price unavailable: tier=%s interval=%s", *key)
            return None

    async def prices(self) -> PlanPrices:
        pm, py, em, ey = await asyncio.gather(
            self._amount(("pro", "monthly")),
            self._amount(("pro", "yearly")),
            self._amount(("enterprise", "monthly")),
            self._amount(("enterprise", "yearly")),
        )
        return PlanPrices(pro=TierPrices(pm, py), enterprise=TierPrices(em, ey))
