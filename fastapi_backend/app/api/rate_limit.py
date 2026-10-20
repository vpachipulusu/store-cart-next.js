"""Rate limit dependencies (ADR-007), attached per route, not as middleware.

Authenticated routes use ``limit_by_subject`` with a dependency that resolves who
is acting (user, organisation or store). Unauthenticated sign-in, sign-up and
password reset use ``limit_auth_attempts``.
"""

import hashlib
import hmac
import ipaddress
import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException, Request, Response, status

from app.api.deps import get_rate_limiter
from app.core.config import settings
from app.core.errors import ErrorResponse
from app.core.rate_limit import (
    AUTH_POLICY,
    RateLimitDecision,
    RateLimiter,
    RateLimitPolicy,
    client_bucket,
)
from app.core.sentry import report_exception

logger = logging.getLogger("storecart.rate_limit")

CLIENT_IP_HEADER = "X-Client-IP"
TOO_MANY_REQUESTS_MESSAGE = "Too many requests"
UNAVAILABLE_MESSAGE = "Service temporarily unavailable"
FAIL_CLOSED_RETRY_AFTER_SECONDS = 5

# Add to a route's ``responses=`` so the OpenAPI schema documents these errors.
RATE_LIMIT_RESPONSES: dict[int | str, dict[str, Any]] = {
    429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
}
RATE_LIMIT_FAIL_CLOSED_RESPONSES: dict[int | str, dict[str, Any]] = {
    **RATE_LIMIT_RESPONSES,
    503: {"model": ErrorResponse, "description": "Rate limiter unavailable"},
}


@dataclass(frozen=True)
class RateLimitSubject:
    """Who is acting: key ``rl:{scope}:{kind}:{id}``."""

    kind: Literal["user", "org", "store"]
    id: str


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def _rate_limit_headers(decision: RateLimitDecision) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(decision.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
        "X-RateLimit-Reset": str(math.ceil(decision.reset_at)),
    }


def _too_many_requests(decision: RateLimitDecision) -> HTTPException:
    retry_after = max(1, math.ceil(decision.reset_at - time.time()))
    headers = {**_rate_limit_headers(decision), "Retry-After": str(retry_after)}
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY_REQUESTS_MESSAGE, headers
    )


def _handle_outage(request: Request, policy: RateLimitPolicy, exc: Exception) -> None:
    """Redis could not answer. Fail closed (503) or open (log and let through)."""
    request_id = request.scope.get("state", {}).get("request_id")
    if policy.fail_closed:
        logger.error(
            "rate limiter unavailable, rejecting request",
            exc_info=exc,
            extra={"request_id": request_id},
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            UNAVAILABLE_MESSAGE,
            {"Retry-After": str(FAIL_CLOSED_RETRY_AFTER_SECONDS)},
        )
    logger.warning(
        "rate limiter unavailable, allowing request",
        exc_info=exc,
        extra={"request_id": request_id},
    )
    report_exception(exc)


async def enforce_rate_limit(
    request: Request,
    response: Response,
    limiter: RateLimiter,
    policy: RateLimitPolicy,
    identifiers: list[str],
) -> None:
    """Hit every identifier; the first denial raises 429. Headers show the tightest."""
    tightest: RateLimitDecision | None = None
    for identifier in identifiers:
        try:
            decision = await limiter.hit(identifier, policy)
        except Exception as exc:  # noqa: BLE001 - any adapter failure follows the fail mode
            _handle_outage(request, policy, exc)
            return
        if not decision.allowed:
            raise _too_many_requests(decision)
        if tightest is None or decision.remaining < tightest.remaining:
            tightest = decision
    if tightest is not None:
        response.headers.update(_rate_limit_headers(tightest))


def limit_by_subject(
    policy: RateLimitPolicy,
    subject_dependency: Callable[..., RateLimitSubject | Awaitable[RateLimitSubject]],
) -> Callable[..., Awaitable[None]]:
    """Dependency factory for authenticated routes (``API_POLICY`` or ``WEBHOOK_POLICY``)."""

    async def dependency(
        request: Request,
        response: Response,
        limiter: RateLimiterDep,
        subject: Annotated[RateLimitSubject, Depends(subject_dependency)],
    ) -> None:
        identifier = f"{policy.scope}:{subject.kind}:{subject.id}"
        await enforce_rate_limit(request, response, limiter, policy, [identifier])

    return dependency


def forwarded_client_ip(request: Request) -> str | None:
    """The validated ``X-Client-IP`` from an internal-key caller, else None."""
    if not getattr(request.state, "internal_authenticated", False):
        return None
    forwarded = request.headers.get(CLIENT_IP_HEADER, "").strip()
    try:
        return str(ipaddress.ip_address(forwarded))
    except ValueError:
        return None


def client_ip(request: Request) -> str:
    """The end-user IP forwarded by Next.js in ``X-Client-IP``, exactly as sent (audit rows use it).

    Only a validated internal service key may establish the forwarding trust boundary.
    Otherwise use the direct peer; ignore inbound X-Forwarded-For. For rate-limit keys use
    ``client_key``, which groups IPv6 by /64.
    """
    forwarded = forwarded_client_ip(request)
    if forwarded is not None:
        return forwarded
    # Missing or malformed: fall back to the direct peer so the call is still limited.
    return request.client.host if request.client else "unknown"


def bucket_of(address: str) -> str:
    """``client_bucket`` that leaves a non-address (the ``unknown`` peer) as it is."""
    try:
        return client_bucket(address)
    except ValueError:
        return address


def client_key(request: Request) -> str:
    """The rate-limit key part for the end user: IPv4 as is, IPv6 grouped by /64 (KAN-252)."""
    return bucket_of(client_ip(request))


def limit_by_client_ip(policy: RateLimitPolicy) -> Callable[..., Awaitable[None]]:
    """Dependency factory for unauthenticated routes with no user to key on.

    Keyed by the forwarded client IP (see ``client_key``). It sets rate-limit headers on
    the injected response; a route that returns its own cacheable ``Response`` drops
    them, so a shared cache never stores one client's counters.
    """

    async def dependency(
        request: Request, response: Response, limiter: RateLimiterDep
    ) -> None:
        identifier = f"{policy.scope}:ip:{client_key(request)}"
        await enforce_rate_limit(request, response, limiter, policy, [identifier])

    return dependency


def limit_by_client_ip_or_store(
    policy: RateLimitPolicy,
) -> Callable[..., Awaitable[None]]:
    """Dependency factory for public store reads that the Next.js server may cache (KAN-75).

    A request forwarding a visitor IP is keyed by that IP. A shared read (internal key, no
    visitor IP: the server filling its per-store cache) is keyed by the ``{slug}`` path
    segment, so one store's cache misses never exhaust the budget of the others.
    """

    async def dependency(
        request: Request, response: Response, limiter: RateLimiterDep
    ) -> None:
        visitor = forwarded_client_ip(request)
        if visitor is not None:
            identifier = f"{policy.scope}:ip:{bucket_of(visitor)}"
        elif getattr(request.state, "internal_authenticated", False):
            slug = str(request.path_params.get("slug", "")).lower()[:63]
            identifier = f"{policy.scope}:store:{slug}"
        else:
            identifier = f"{policy.scope}:ip:{client_key(request)}"
        await enforce_rate_limit(request, response, limiter, policy, [identifier])

    return dependency


def email_digest(email: str) -> str:
    key = settings.RATE_LIMIT_EMAIL_KEY
    if not key:
        raise HTTPException(503, UNAVAILABLE_MESSAGE, {"Retry-After": "5"})
    return hmac.new(
        key.get_secret_value().encode(), email.strip().lower().encode(), hashlib.sha256
    ).hexdigest()


async def _no_email() -> None:
    return None


def limit_auth_attempts(
    email_dependency: Callable[..., str | None | Awaitable[str | None]] | None = None,
) -> Callable[..., Awaitable[None]]:
    """Dependency factory for sign-in, sign-up and password reset (``AUTH_POLICY``).

    Limits by client IP and, when ``email_dependency`` yields an email, by the
    keyed HMAC of that email too. Fails closed when Redis is down.
    """

    async def dependency(
        request: Request,
        response: Response,
        limiter: RateLimiterDep,
        email: Annotated[str | None, Depends(email_dependency or _no_email)],
    ) -> None:
        identifiers = [f"{AUTH_POLICY.scope}:ip:{client_key(request)}"]
        if email:
            identifiers.append(f"{AUTH_POLICY.scope}:email:{email_digest(email)}")
        await enforce_rate_limit(request, response, limiter, AUTH_POLICY, identifiers)

    return dependency
