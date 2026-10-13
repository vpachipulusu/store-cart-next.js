import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from app.api import deps
from app.core.rate_limit import (
    API_POLICY,
    REDIS_TIMEOUT_SECONDS,
    DisabledRateLimiter,
    RateLimiterUnavailable,
    UpstashRateLimiter,
)


class FakeRedis:
    def __init__(self, delay: float = 0, error: Exception | None = None) -> None:
        self._delay = delay
        self._error = error

    async def ping(self) -> bool:
        await asyncio.sleep(self._delay)
        if self._error:
            raise self._error
        return True


class FakeSlidingWindow:
    def __init__(self, response: Any = None, delay: float = 0) -> None:
        self.response = response
        self.delay = delay
        self.identifiers: list[str] = []

    async def limit(self, identifier: str) -> Any:
        self.identifiers.append(identifier)
        await asyncio.sleep(self.delay)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def limiter_with(
    ratelimit: FakeSlidingWindow, redis: FakeRedis | None = None, timeout: float = 0.05
) -> UpstashRateLimiter:
    limiter = UpstashRateLimiter(redis or FakeRedis(), timeout_seconds=timeout)  # type: ignore[arg-type]
    limiter._limiters[API_POLICY] = ratelimit  # type: ignore[assignment]
    return limiter


def test_redis_timeout_is_200_ms() -> None:
    assert REDIS_TIMEOUT_SECONDS == 0.2


async def test_hit_maps_the_upstash_response() -> None:
    fake = FakeSlidingWindow(
        SimpleNamespace(allowed=True, limit=100, remaining=7, reset=12.5)
    )

    decision = await limiter_with(fake).hit("api:user:u1", API_POLICY)

    assert (decision.allowed, decision.limit, decision.remaining) == (True, 100, 7)
    assert decision.reset_at == 12.5
    assert fake.identifiers == ["api:user:u1"]


async def test_hit_clamps_negative_remaining_to_zero() -> None:
    fake = FakeSlidingWindow(
        SimpleNamespace(allowed=False, limit=100, remaining=-3, reset=1)
    )

    decision = await limiter_with(fake).hit("x", API_POLICY)

    assert (decision.allowed, decision.remaining) == (False, 0)


async def test_hit_raises_unavailable_on_timeout() -> None:
    fake = FakeSlidingWindow(SimpleNamespace(), delay=1)

    with pytest.raises(RateLimiterUnavailable):
        await limiter_with(fake, timeout=0.01).hit("x", API_POLICY)


async def test_hit_raises_unavailable_on_redis_error() -> None:
    fake = FakeSlidingWindow(ConnectionError("down"))

    with pytest.raises(RateLimiterUnavailable):
        await limiter_with(fake).hit("x", API_POLICY)


async def test_ping_is_false_on_error_or_timeout_and_true_otherwise() -> None:
    fake = FakeSlidingWindow()
    assert await limiter_with(fake, FakeRedis()).ping() is True
    assert await limiter_with(fake, FakeRedis(error=OSError("x"))).ping() is False
    assert await limiter_with(fake, FakeRedis(delay=1), timeout=0.01).ping() is False


def test_limiter_is_built_once_per_policy_with_the_rl_prefix() -> None:
    limiter = UpstashRateLimiter.from_credentials("https://x.upstash.io", "token")

    first = limiter._limiter_for(API_POLICY)

    assert limiter._limiter_for(API_POLICY) is first
    assert first._prefix == "rl"


async def test_disabled_limiter_allows_and_pings_ok() -> None:
    limiter = DisabledRateLimiter()

    assert (await limiter.hit("x", API_POLICY)).allowed is True
    assert await limiter.ping() is True


def test_get_rate_limiter_is_disabled_without_upstash_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps, "_rate_limiter", None)
    monkeypatch.setattr(deps.settings, "UPSTASH_REDIS_REST_URL", None)

    assert isinstance(deps.get_rate_limiter(), DisabledRateLimiter)


def test_get_rate_limiter_builds_upstash_and_caches_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps, "_rate_limiter", None)
    monkeypatch.setattr(deps.settings, "UPSTASH_REDIS_REST_URL", "https://x.upstash.io")
    monkeypatch.setattr(deps.settings, "UPSTASH_REDIS_REST_TOKEN", SecretStr("t"))

    limiter = deps.get_rate_limiter()

    assert isinstance(limiter, UpstashRateLimiter)
    assert deps.get_rate_limiter() is limiter
