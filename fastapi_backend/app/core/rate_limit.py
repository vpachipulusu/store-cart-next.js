"""Rate limiting primitives (ADR-007): policies, the limiter seam and Upstash adapter.

Counters live in Upstash Redis (HTTP), never in process memory. The limiter sits
behind the small ``RateLimiter`` protocol so tests inject an in-memory fake.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx
from upstash_ratelimit.asyncio import Ratelimit, SlidingWindow
from upstash_redis.asyncio import Redis

# Hard cap on any Redis round trip (architect decision). Past this, the
# policy's fail mode decides what happens.
REDIS_TIMEOUT_SECONDS = 0.2
# Fail-closed policies (sign-in) lock users out when Redis is slow, so they get a budget that
# survives a cold TCP+TLS connect to a distant region (KAN-243). Fail-open policies keep 200 ms.
FAIL_CLOSED_REDIS_TIMEOUT_SECONDS = 1.0

# A replaced client is closed after this grace period so in-flight calls on it can finish.
CLOSE_GRACE_SECONDS = 5.0
# A retry needs at least this much of the shared deadline left, or it would be cut off anyway.
MIN_RETRY_REMAINING_SECONDS = 0.2

logger = logging.getLogger("storecart.rate_limit")

# The request never reached Redis, so retrying cannot count a hit twice.
_RETRYABLE_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)

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
# Public storefront lookup (KAN-65): keyed by client IP, no user is attached.
STOREFRONT_POLICY = RateLimitPolicy(
    "storefront", limit=120, window_seconds=60, fail_closed=False
)
# Public platform settings (KAN-205): keyed by client IP, like the storefront lookup.
PUBLIC_SETTINGS_POLICY = RateLimitPolicy(
    "public_settings", limit=120, window_seconds=60, fail_closed=False
)
# Merchant retry of a FAILED store (KAN-242): hit once per user and once per store, so one
# merchant cannot spam many stores and nobody can spam one store. Fail closed: a retry
# queues external work, so an outage must not lift the limit.
RETRY_PROVISIONING_POLICY = RateLimitPolicy(
    "retry_provisioning", limit=5, window_seconds=10 * 60, fail_closed=True
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


class DisabledRateLimiter:
    """Used when Upstash is not configured (local dev and tests): allows everything."""

    enabled = False

    async def hit(self, identifier: str, policy: RateLimitPolicy) -> RateLimitDecision:
        return RateLimitDecision(True, policy.limit, policy.limit, 0.0)


class UpstashRateLimiter:
    """Sliding-window limiter over Upstash Redis REST.

    The REST client wraps one httpx pool. On a serverless runtime that pool can go stale
    (KAN-243: ``ConnectError`` "Device or resource busy"), so a client that fails at the
    transport level is replaced once (concurrent failures on the same client cause one
    rebuild), the client is replaced when the event loop changes, and a fail-closed call
    is retried once on a connect error within one shared deadline. A plain timeout means
    slow, not broken: it is neither retried nor does it discard a warm connection.

    Assumes one serving event loop; requests from several loops would rebuild on each switch.
    """

    enabled = True

    def __init__(
        self,
        redis: Redis,
        timeout_seconds: float = REDIS_TIMEOUT_SECONDS,
        redis_factory: Callable[[], Redis] | None = None,
        fail_closed_timeout_seconds: float = FAIL_CLOSED_REDIS_TIMEOUT_SECONDS,
        close_grace_seconds: float = CLOSE_GRACE_SECONDS,
    ) -> None:
        self._redis = redis
        self._timeout = timeout_seconds
        self._fail_closed_timeout = fail_closed_timeout_seconds
        self._close_grace = close_grace_seconds
        self._redis_factory = redis_factory
        self._loop: asyncio.AbstractEventLoop | None = None
        self._limiters: dict[RateLimitPolicy, Ratelimit] = {}
        self._closing: set[asyncio.Task[None]] = set()

    @classmethod
    def from_credentials(cls, url: str, token: str) -> "UpstashRateLimiter":
        # rest_retries=0: the client's default retry sleeps seconds, far above the
        # latency budget. The caller applies the fail mode (and one retry) instead.
        def factory() -> Redis:
            return Redis(url=url, token=token, rest_retries=0)

        return cls(factory(), redis_factory=factory)

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

    def _replace_client(self) -> Redis | None:
        """Swap in a fresh client; returns the old one, or None when no factory is set."""
        if self._redis_factory is None:
            return None
        old = self._redis
        self._redis = self._redis_factory()
        self._limiters = {}
        return old

    def _rebuild_if_current(self, failed: Redis) -> None:
        # A late failure from an already replaced client must not discard the healthy new one.
        if self._redis is failed:
            old = self._replace_client()
            if old is not None:
                self._close_later(old)

    def _close_later(self, old: Redis) -> None:
        close = getattr(old, "close", None)
        if close is None:
            return

        async def close_after_grace() -> None:
            # Calls still awaiting on the old client get time to finish first.
            await asyncio.sleep(self._close_grace)
            with contextlib.suppress(Exception):
                await close()

        task = asyncio.get_running_loop().create_task(close_after_grace())
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    def _use_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._loop is not None and self._loop is not loop:
            # The old client belongs to a loop that may be gone: drop it, do not close it.
            self._replace_client()
        self._loop = loop

    async def _limit(
        self, identifier: str, policy: RateLimitPolicy, timeout: float
    ) -> RateLimitDecision:
        response = await asyncio.wait_for(
            self._limiter_for(policy).limit(identifier), timeout
        )
        return RateLimitDecision(
            allowed=response.allowed,
            limit=response.limit,
            remaining=max(response.remaining, 0),
            reset_at=float(response.reset),
        )

    async def hit(self, identifier: str, policy: RateLimitPolicy) -> RateLimitDecision:
        loop = asyncio.get_running_loop()
        self._use_loop(loop)
        budget = self._fail_closed_timeout if policy.fail_closed else self._timeout
        deadline = loop.time() + budget
        attempts = 2 if policy.fail_closed and self._redis_factory else 1
        attempt = 0
        while True:
            attempt += 1
            client = self._redis
            try:
                return await self._limit(identifier, policy, deadline - loop.time())
            except Exception as exc:
                # Class and policy only: the message and identifier can carry secrets or PII.
                logger.warning(
                    "rate limiter call failed: policy=%s error=%s attempt=%d/%d",
                    policy.scope,
                    type(exc).__name__,
                    attempt,
                    attempts,
                )
                if isinstance(exc, httpx.TransportError):
                    self._rebuild_if_current(client)
                can_retry = (
                    attempt < attempts
                    and isinstance(exc, _RETRYABLE_ERRORS)
                    and deadline - loop.time() >= MIN_RETRY_REMAINING_SECONDS
                )
                if not can_retry:
                    raise RateLimiterUnavailable("rate limit check failed") from exc


# Personal data export (KAN-120): assembles every row the user owns, so it is capped hard
# per user. Fail closed: an outage must not lift the limit on an expensive read.
EXPORT_POLICY = RateLimitPolicy(
    "me_export", limit=3, window_seconds=60 * 60, fail_closed=True
)
