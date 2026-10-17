import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from upstash_ratelimit.utils import ms_to_s

from app.api import deps
from app.core.rate_limit import (
    API_POLICY,
    AUTH_POLICY,
    REDIS_TIMEOUT_SECONDS,
    DisabledRateLimiter,
    RateLimiterUnavailable,
    RateLimitPolicy,
    UpstashRateLimiter,
)


class FakeRedis:
    """The adapter only hands the client to upstash-ratelimit; no calls are made."""


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


def test_limiter_is_built_once_per_policy_with_the_rl_prefix() -> None:
    limiter = UpstashRateLimiter.from_credentials("https://x.upstash.io", "token")

    first = limiter._limiter_for(API_POLICY)

    assert limiter._limiter_for(API_POLICY) is first
    assert first._prefix == "rl"


async def test_disabled_limiter_allows_everything() -> None:
    limiter = DisabledRateLimiter()

    assert (await limiter.hit("x", API_POLICY)).allowed is True


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


def test_upstash_reset_is_unix_seconds_not_milliseconds() -> None:
    # upstash-ratelimit 1.2.0 documents Response.reset as "Unix timestamp in
    # seconds" and builds it with ms_to_s. If that ever changes, the
    # X-RateLimit-Reset / Retry-After conversion would be wrong: fail loudly.
    assert ms_to_s(1_700_000_000_500) == 1_700_000_000.5


async def test_decision_reset_at_keeps_upstash_seconds_unchanged() -> None:
    fake = FakeSlidingWindow(
        SimpleNamespace(allowed=True, limit=5, remaining=4, reset=1_700_000_000.5)
    )

    decision = await limiter_with(fake).hit("x", API_POLICY)

    assert decision.reset_at == 1_700_000_000.5


# --- KAN-243: a stale or broken Redis client must not lock everyone out ---------------


class ClientFactory:
    """Hands out one scripted FakeSlidingWindow per rebuilt client."""

    def __init__(self, *windows: FakeSlidingWindow) -> None:
        self._windows = list(windows)
        self.built = 0

    def __call__(self) -> FakeRedis:
        self.built += 1
        return FakeRedis()

    def window(self) -> FakeSlidingWindow:
        return self._windows.pop(0)


def rebuilding_limiter(
    policy: RateLimitPolicy, *windows: FakeSlidingWindow
) -> tuple[UpstashRateLimiter, ClientFactory]:
    factory = ClientFactory(*windows)
    limiter = UpstashRateLimiter(
        factory(),  # type: ignore[arg-type]
        redis_factory=factory,  # type: ignore[arg-type]
    )

    def next_limiter(self: UpstashRateLimiter, _policy: RateLimitPolicy) -> Any:
        window = self._limiters.get(_policy)
        if window is None:
            window = factory.window()
            self._limiters[_policy] = window  # type: ignore[assignment]
        return window

    limiter._limiter_for = next_limiter.__get__(limiter)  # type: ignore[method-assign]
    return limiter, factory


OK = SimpleNamespace(allowed=True, limit=5, remaining=4, reset=1)


async def test_auth_hit_rebuilds_the_client_and_retries_after_a_connect_error() -> None:
    limiter, factory = rebuilding_limiter(
        AUTH_POLICY,
        FakeSlidingWindow(httpx.ConnectError("[Errno 16] Device or resource busy")),
        FakeSlidingWindow(OK),
    )

    decision = await limiter.hit("auth:ip:1", AUTH_POLICY)

    assert decision.allowed is True
    assert factory.built == 2  # the initial client and one rebuild


async def test_auth_hit_is_unavailable_when_the_retry_also_fails() -> None:
    first = FakeSlidingWindow(httpx.ConnectError("down"))
    second = FakeSlidingWindow(httpx.ConnectError("still down"))
    limiter, factory = rebuilding_limiter(AUTH_POLICY, first, second)

    with pytest.raises(RateLimiterUnavailable):
        await limiter.hit("auth:ip:1", AUTH_POLICY)

    assert (len(first.identifiers), len(second.identifiers)) == (1, 1)  # one retry only
    assert (
        factory.built == 3
    )  # initial, rebuilt for the retry, rebuilt for the next request


async def test_a_fail_open_policy_is_not_retried() -> None:
    only = FakeSlidingWindow(httpx.ConnectError("down"))
    limiter, factory = rebuilding_limiter(API_POLICY, only)

    with pytest.raises(RateLimiterUnavailable):
        await limiter.hit("api:user:u1", API_POLICY)

    assert only.identifiers == ["api:user:u1"]  # called once, never retried
    assert factory.built == 2  # a transport failure still discards the broken client


async def test_a_timeout_is_neither_retried_nor_discards_the_warm_client() -> None:
    slow = FakeSlidingWindow(SimpleNamespace(), delay=1)
    limiter, factory = rebuilding_limiter(AUTH_POLICY, slow)
    limiter._fail_closed_timeout = 0.01

    with pytest.raises(RateLimiterUnavailable):
        await limiter.hit("auth:ip:1", AUTH_POLICY)

    assert slow.identifiers == ["auth:ip:1"] and factory.built == 1


async def test_a_retry_that_would_outlive_the_shared_deadline_is_skipped() -> None:
    first = FakeSlidingWindow(httpx.ConnectError("down"), delay=0.4)
    limiter, _ = rebuilding_limiter(AUTH_POLICY, first, FakeSlidingWindow(OK))
    limiter._fail_closed_timeout = 0.5  # 0.1 s left after the first attempt

    with pytest.raises(RateLimiterUnavailable):
        await limiter.hit("auth:ip:1", AUTH_POLICY)

    assert first.identifiers == ["auth:ip:1"]


async def test_concurrent_failures_on_one_client_cause_a_single_rebuild() -> None:
    limiter, factory = rebuilding_limiter(
        AUTH_POLICY,
        FakeSlidingWindow(httpx.ConnectError("down"), delay=0.02),
        FakeSlidingWindow(OK),
    )

    decisions = await asyncio.gather(
        *(limiter.hit(f"auth:ip:{n}", AUTH_POLICY) for n in range(20))
    )

    assert all(decision.allowed for decision in decisions)
    assert factory.built == 2  # the initial client plus exactly one replacement


async def test_a_replaced_client_is_closed_after_the_grace_period() -> None:
    closed: list[bool] = []

    class ClosableRedis(FakeRedis):
        async def close(self) -> None:
            closed.append(True)

    factory = ClientFactory(
        FakeSlidingWindow(httpx.ConnectError("down")), FakeSlidingWindow(OK)
    )
    limiter = UpstashRateLimiter(
        ClosableRedis(),  # type: ignore[arg-type]
        redis_factory=factory,  # type: ignore[arg-type]
        close_grace_seconds=0,
    )

    def window_for(policy: RateLimitPolicy) -> Any:
        return limiter._limiters.setdefault(policy, factory.window())  # type: ignore[arg-type]

    limiter._limiter_for = window_for  # type: ignore[method-assign,assignment]

    await limiter.hit("auth:ip:1", AUTH_POLICY)
    await asyncio.sleep(0.01)

    assert closed == [True]


async def test_a_failed_call_logs_policy_and_error_class_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    limiter, _ = rebuilding_limiter(
        AUTH_POLICY,
        FakeSlidingWindow(httpx.ConnectError("secret-token-text")),
        FakeSlidingWindow(OK),
    )

    with caplog.at_level("WARNING", logger="storecart.rate_limit"):
        await limiter.hit("auth:email:digest", AUTH_POLICY)

    text = " ".join(record.getMessage() for record in caplog.records)
    assert "auth" in text and "ConnectError" in text
    assert "secret-token-text" not in text and "digest" not in text


async def test_a_client_from_another_event_loop_is_rebuilt() -> None:
    limiter, factory = rebuilding_limiter(
        AUTH_POLICY, FakeSlidingWindow(OK), FakeSlidingWindow(OK)
    )
    limiter._loop = object()  # type: ignore[assignment]  # as if built on an earlier loop

    await limiter.hit("auth:ip:1", AUTH_POLICY)

    assert factory.built == 2


async def test_the_same_event_loop_does_not_rebuild_the_client() -> None:
    limiter, factory = rebuilding_limiter(AUTH_POLICY, FakeSlidingWindow(OK))

    await limiter.hit("auth:ip:1", AUTH_POLICY)
    await limiter.hit("auth:ip:2", AUTH_POLICY)

    assert factory.built == 1


async def test_a_transport_error_that_is_not_a_connect_error_is_not_retried() -> None:
    first = FakeSlidingWindow(httpx.ReadError("reset"))
    limiter, factory = rebuilding_limiter(AUTH_POLICY, first, FakeSlidingWindow(OK))

    with pytest.raises(RateLimiterUnavailable):
        await limiter.hit("auth:ip:1", AUTH_POLICY)

    assert first.identifiers == ["auth:ip:1"] and factory.built == 2


async def test_a_connect_timeout_is_retried_like_a_connect_error() -> None:
    limiter, _ = rebuilding_limiter(
        AUTH_POLICY,
        FakeSlidingWindow(httpx.ConnectTimeout("slow")),
        FakeSlidingWindow(OK),
    )

    assert (await limiter.hit("auth:ip:1", AUTH_POLICY)).allowed is True


async def test_a_limiter_without_a_factory_is_never_retried_or_rebuilt() -> None:
    fake = FakeSlidingWindow(httpx.ConnectError("down"))
    limiter = UpstashRateLimiter(FakeRedis())  # type: ignore[arg-type]
    limiter._limiters[AUTH_POLICY] = fake  # type: ignore[assignment]

    with pytest.raises(RateLimiterUnavailable):
        await limiter.hit("auth:ip:1", AUTH_POLICY)

    assert fake.identifiers == ["auth:ip:1"]


async def test_each_policy_gets_its_own_latency_budget() -> None:
    # 0.3 s is over the 0.2 s fail-open cap and under the 1 s fail-closed one.
    slow = SimpleNamespace(allowed=True, limit=5, remaining=4, reset=1)

    closed, _ = rebuilding_limiter(AUTH_POLICY, FakeSlidingWindow(slow, delay=0.3))
    assert (await closed.hit("auth:ip:1", AUTH_POLICY)).allowed is True

    open_, _ = rebuilding_limiter(API_POLICY, FakeSlidingWindow(slow, delay=0.3))
    open_._timeout = REDIS_TIMEOUT_SECONDS
    with pytest.raises(RateLimiterUnavailable):
        await open_.hit("api:user:u1", API_POLICY)


def test_from_credentials_wires_a_factory_that_builds_fresh_clients() -> None:
    limiter = UpstashRateLimiter.from_credentials("https://x.upstash.io", "token")

    assert limiter._redis_factory is not None
    assert limiter._redis_factory() is not limiter._redis
