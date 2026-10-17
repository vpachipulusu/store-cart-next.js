"""Price cache (KAN-119): reuse for the TTL, never cache a miss or a failure."""

import pytest

from app.core.stripe_billing import StripeError
from app.core.stripe_prices import StripePrice
from app.services.price_cache import CachedPriceReader, PriceCache

PRICE = StripePrice(2900, "GBP")


class Reader:
    def __init__(self, price: StripePrice | None = PRICE) -> None:
        self.price, self.calls, self.fail = price, 0, False

    async def get_price(self, price_id: str) -> StripePrice | None:
        self.calls += 1
        if self.fail:
            raise StripeError("Stripe request failed")
        return self.price


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def build(reader: Reader) -> tuple[CachedPriceReader, Clock]:
    clock = Clock()
    return CachedPriceReader(reader, PriceCache(300.0, clock)), clock


async def test_second_read_within_the_ttl_does_not_call_stripe() -> None:
    reader = Reader()
    cached, clock = build(reader)

    assert await cached.get_price("price_a") == PRICE
    clock.now += 299
    assert await cached.get_price("price_a") == PRICE

    assert reader.calls == 1


async def test_read_after_the_ttl_calls_stripe_again() -> None:
    reader = Reader()
    cached, clock = build(reader)
    await cached.get_price("price_a")

    clock.now += 300
    await cached.get_price("price_a")

    assert reader.calls == 2


async def test_each_price_id_is_cached_separately() -> None:
    reader = Reader()
    cached, _ = build(reader)

    await cached.get_price("price_a")
    await cached.get_price("price_b")

    assert reader.calls == 2


async def test_a_price_without_an_amount_is_not_cached() -> None:
    reader = Reader(None)
    cached, _ = build(reader)

    await cached.get_price("price_a")
    await cached.get_price("price_a")

    assert reader.calls == 2


async def test_a_failure_is_raised_and_not_cached() -> None:
    reader = Reader()
    reader.fail = True
    cached, _ = build(reader)

    with pytest.raises(StripeError):
        await cached.get_price("price_a")
    reader.fail = False

    assert await cached.get_price("price_a") == PRICE


def test_clear_forgets_everything() -> None:
    cache = PriceCache()
    cache.put("price_a", PRICE)

    cache.clear()

    assert cache.get("price_a") is None
