"""Short in-process cache of Stripe price details (KAN-119).

The admin revenue endpoint and the subscriptions page read the same few configured
prices on every request. Prices change rarely, so a successful read is reused for a few
minutes (per process; a failed or empty read is never cached).
"""

import time
from collections.abc import Callable

from app.core.stripe_prices import StripePrice, StripePriceDetailsReader

PRICE_CACHE_TTL_SECONDS = 300.0


class PriceCache:
    def __init__(
        self,
        ttl_seconds: float = PRICE_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl, self._clock = ttl_seconds, clock
        self._items: dict[str, tuple[float, StripePrice]] = {}

    def get(self, price_id: str) -> StripePrice | None:
        found = self._items.get(price_id)
        if found is None or self._clock() - found[0] >= self._ttl:
            return None
        return found[1]

    def put(self, price_id: str, price: StripePrice) -> None:
        self._items[price_id] = (self._clock(), price)

    def clear(self) -> None:
        self._items.clear()


class CachedPriceReader:
    def __init__(self, reader: StripePriceDetailsReader, cache: PriceCache) -> None:
        self._reader, self._cache = reader, cache

    async def get_price(self, price_id: str) -> StripePrice | None:
        cached = self._cache.get(price_id)
        if cached is not None:
            return cached
        price = await self._reader.get_price(price_id)
        if price is not None:
            self._cache.put(price_id, price)
        return price


SHARED_PRICE_CACHE = PriceCache()
