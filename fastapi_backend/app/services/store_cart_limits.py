"""The per-store cap on new anonymous carts (KAN-252). No FastAPI imports.

A cart row lives 30 days and creating one needs no account, so the per-client limit alone cannot
stop one client from filling a store's database. ``RateLimitedCartCreation`` hits one counter per
store id (``cart_create:store:{id}``, hourly) every time a request is about to start a new cart.

* Over the cap: ``CartCreationLimited`` (the route answers 429 with ``Retry-After``).
* Limiter down (Redis unreachable or too slow): ``CartCreationUnavailable`` (503). Creation fails
  closed because the cap protects storage; carts that already exist never reach the guard, so
  shoppers with a cart keep adding, changing and reading.
* Limiter not configured (local development): everything is admitted.
"""

import logging
import math
import time
from collections.abc import Callable
from typing import Protocol

from app.core.rate_limit import RateLimiter, RateLimitPolicy
from app.core.sentry import report_exception

logger = logging.getLogger("storecart.cart_limits")


class CartCreationLimited(Exception):
    """The store has started as many carts as one hour allows."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Cart creation limit reached")
        self.retry_after_seconds = retry_after_seconds


class CartCreationUnavailable(Exception):
    """The creation cap cannot be checked right now, so no new cart is started."""


class CartCreationGuard(Protocol):
    async def admit(self) -> None:
        """Return when one more cart may be created; raise otherwise."""
        ...


class RateLimitedCartCreation:
    def __init__(
        self,
        limiter: RateLimiter,
        store_id: str,
        policy: RateLimitPolicy,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._limiter = limiter
        self._identifier = f"{policy.scope}:store:{store_id}"
        self._policy = policy
        self._clock = clock

    async def admit(self) -> None:
        try:
            decision = await self._limiter.hit(self._identifier, self._policy)
        except Exception as exc:  # noqa: BLE001 - any adapter failure follows the fail mode
            # The identifier carries only the store id; log the class, never the message.
            logger.error("cart creation cap unavailable: error=%s", type(exc).__name__)
            report_exception(exc)
            raise CartCreationUnavailable from None
        if not decision.allowed:
            retry_after = max(1, math.ceil(decision.reset_at - self._clock()))
            raise CartCreationLimited(retry_after)
