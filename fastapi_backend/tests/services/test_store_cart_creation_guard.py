"""The per-store cart creation cap (KAN-252) over the limiter seam, no Redis."""

import pytest

from app.core.rate_limit import CART_CREATE_POLICY, DisabledRateLimiter, RateLimitPolicy
from app.services.store_cart_limits import (
    CartCreationLimited,
    CartCreationUnavailable,
    RateLimitedCartCreation,
)
from tests.fakes import FakeRateLimiter, RaisingRateLimiter

STORE = "abcdefgh12345678abcdefgh"
TINY = RateLimitPolicy("cart_create", limit=2, window_seconds=3600, fail_closed=True)


def test_the_policy_is_hourly_and_fails_closed() -> None:
    assert CART_CREATE_POLICY.window_seconds == 3600
    assert CART_CREATE_POLICY.fail_closed is True
    assert CART_CREATE_POLICY.scope == "cart_create"


async def test_creations_up_to_the_cap_pass_and_are_keyed_by_store_id() -> None:
    limiter = FakeRateLimiter()
    guard = RateLimitedCartCreation(limiter, STORE, TINY)

    await guard.admit()
    await guard.admit()

    assert [identifier for identifier, _ in limiter.hits] == [
        f"cart_create:store:{STORE}"
    ] * 2


async def test_the_creation_over_the_cap_is_limited_with_a_retry_delay() -> None:
    limiter = FakeRateLimiter(reset_at=1_000.0)
    guard = RateLimitedCartCreation(limiter, STORE, TINY, clock=lambda: 940.0)
    await guard.admit()
    await guard.admit()

    with pytest.raises(CartCreationLimited) as caught:
        await guard.admit()

    assert caught.value.retry_after_seconds == 60


async def test_one_stores_cap_does_not_use_up_anothers() -> None:
    limiter = FakeRateLimiter()
    first = RateLimitedCartCreation(limiter, STORE, TINY)
    second = RateLimitedCartCreation(limiter, "otherstore", TINY)
    await first.admit()
    await first.admit()

    await second.admit()


async def test_a_redis_outage_refuses_creation_instead_of_lifting_the_cap() -> None:
    guard = RateLimitedCartCreation(RaisingRateLimiter(), STORE, TINY)

    with pytest.raises(CartCreationUnavailable):
        await guard.admit()


async def test_an_unconfigured_limiter_allows_creation_as_in_local_development() -> (
    None
):
    guard = RateLimitedCartCreation(DisabledRateLimiter(), STORE, TINY)

    await guard.admit()
