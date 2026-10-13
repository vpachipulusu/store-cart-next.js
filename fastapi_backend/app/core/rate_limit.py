"""Rate limiting primitives (ADR-007): policies, the limiter seam and Upstash adapter.

Counters live in Upstash Redis (HTTP), never in process memory. The limiter sits
behind the small ``RateLimiter`` protocol so tests inject an in-memory fake.
"""

import asyncio
from dataclasses import dataclass
from typing import Protocol

from upstash_ratelimit.asyncio import Ratelimit, SlidingWindow
from upstash_redis.asyncio import Redis

# Hard cap on any Redis round trip (architect decision). Past this, the
# policy's fail mode decides what happens.
REDIS_TIMEOUT_SECONDS = 0.2

# Every key is stored as rl:{scope}:{user|org|store|ip|email}:{id}.
KEY_PREFIX = "rl"


@dataclass(frozen=True)
class RateLimitPolicy:
    """One limit. ``fail_closed`` decides what a Redis outage means."""

    scope: str
    limit: int
    window_seconds: int
    fail_closed: bool


# Numbers match RATE_LIMIT_CONFIGS in nextjs-frontend/src/lib/middleware/rate-limit.ts.
AUTH_POLICY = RateLimitPolicy("auth", limit=5, window_seconds=15 * 60, fail_closed=True)
API_POLICY = RateLimitPolicy("api", limit=100, window_seconds=60, fail_closed=False)
WEBHOOK_POLICY = RateLimitPolicy(
    "webhook", limit=200, window_seconds=60, fail_closed=False
)


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_at: float  # Unix timestamp in seconds


class RateLimiterUnavailable(Exception):
    """Redis could not answer in time (timeout, network or server error)."""


class RateLimiter(Protocol):
    async def hit(
        self, identifier: str, policy: RateLimitPolicy
    ) -> RateLimitDecision: ...

    async def ping(self) -> bool: ...


class DisabledRateLimiter:
    """Used when Upstash is not configured (local dev and tests): allows everything."""

    enabled = False

    async def hit(self, identifier: str, policy: RateLimitPolicy) -> RateLimitDecision:
        return RateLimitDecision(True, policy.limit, policy.limit, 0.0)

    async def ping(self) -> bool:
        return True


class UpstashRateLimiter:
    """Sliding-window limiter over Upstash Redis REST."""

    enabled = True

    def __init__(
        self, redis: Redis, timeout_seconds: float = REDIS_TIMEOUT_SECONDS
    ) -> None:
        self._redis = redis
        self._timeout = timeout_seconds
        self._limiters: dict[RateLimitPolicy, Ratelimit] = {}

    @classmethod
    def from_credentials(cls, url: str, token: str) -> "UpstashRateLimiter":
        # rest_retries=0: the client's default retry sleeps seconds, far above the
        # 200 ms budget. The caller applies the fail mode instead.
        return cls(Redis(url=url, token=token, rest_retries=0))

    def _limiter_for(self, policy: RateLimitPolicy) -> Ratelimit:
        limiter = self._limiters.get(policy)
        if limiter is None:
            limiter = Ratelimit(
                self._redis,
                SlidingWindow(policy.limit, policy.window_seconds, "s"),
                prefix=KEY_PREFIX,
            )
            self._limiters[policy] = limiter
        return limiter

    async def hit(self, identifier: str, policy: RateLimitPolicy) -> RateLimitDecision:
        try:
            response = await asyncio.wait_for(
                self._limiter_for(policy).limit(identifier), self._timeout
            )
        except Exception as exc:
            raise RateLimiterUnavailable("rate limit check failed") from exc
        return RateLimitDecision(
            allowed=response.allowed,
            limit=response.limit,
            remaining=max(response.remaining, 0),
            reset_at=float(response.reset),
        )

    async def ping(self) -> bool:
        try:
            await asyncio.wait_for(self._redis.ping(), self._timeout)
        except Exception:  # noqa: BLE001 - any failure means not ready
            return False
        return True
