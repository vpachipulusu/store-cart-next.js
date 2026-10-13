import logging
import math
import time

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_rate_limiter
from app.api.rate_limit import (
    RateLimitSubject,
    email_digest,
    limit_auth_attempts,
    limit_by_subject,
)
from app.core import sentry as sentry_module
from app.core.errors import register_error_handlers
from app.core.rate_limit import (
    API_POLICY,
    AUTH_POLICY,
    WEBHOOK_POLICY,
    RateLimitPolicy,
)
from app.core.request_id import RequestIdMiddleware
from tests.fakes import FakeRateLimiter, RaisingRateLimiter, as_limiter

SMALL_OPEN = RateLimitPolicy("api", limit=2, window_seconds=60, fail_closed=False)


def user_subject() -> RateLimitSubject:
    return RateLimitSubject("user", "u1")


def store_subject() -> RateLimitSubject:
    return RateLimitSubject("store", "s9")


def body_email() -> str:
    return "Ada@Example.com "


def build_app(limiter: FakeRateLimiter | RaisingRateLimiter) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(limiter)

    @app.get("/api", dependencies=[Depends(limit_by_subject(SMALL_OPEN, user_subject))])
    async def api() -> dict[str, bool]:
        return {"ok": True}

    @app.get(
        "/hook", dependencies=[Depends(limit_by_subject(WEBHOOK_POLICY, store_subject))]
    )
    async def hook() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/signin", dependencies=[Depends(limit_auth_attempts(body_email))])
    async def signin() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/reset", dependencies=[Depends(limit_auth_attempts())])
    async def reset() -> dict[str, bool]:
        return {"ok": True}

    return app


def client_for(limiter: FakeRateLimiter | RaisingRateLimiter) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=build_app(limiter)), base_url="http://test"
    )


def test_policies_match_the_boilerplate_config() -> None:
    assert (AUTH_POLICY.limit, AUTH_POLICY.window_seconds) == (5, 15 * 60)
    assert (API_POLICY.limit, API_POLICY.window_seconds) == (100, 60)
    assert (WEBHOOK_POLICY.limit, WEBHOOK_POLICY.window_seconds) == (200, 60)
    assert AUTH_POLICY.fail_closed
    assert not API_POLICY.fail_closed
    assert not WEBHOOK_POLICY.fail_closed


async def test_allowed_request_carries_rate_limit_headers() -> None:
    async with client_for(FakeRateLimiter(reset_at=4_000_000_000.0)) as client:
        response = await client.get("/api")

    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "2"
    assert response.headers["X-RateLimit-Remaining"] == "1"
    assert response.headers["X-RateLimit-Reset"] == "4000000000"


async def test_exceeding_the_limit_returns_429_in_the_error_envelope() -> None:
    reset_at = time.time() + 30
    async with client_for(FakeRateLimiter(reset_at=reset_at)) as client:
        await client.get("/api")
        await client.get("/api")
        response = await client.get("/api")

    assert response.status_code == 429
    assert response.json() == {"success": False, "error": "Too many requests"}
    assert response.headers["X-RateLimit-Limit"] == "2"
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert int(response.headers["X-RateLimit-Reset"]) >= int(reset_at)
    assert 1 <= int(response.headers["Retry-After"]) <= 31
    assert "X-Request-ID" in response.headers


async def test_retry_after_is_at_least_one_second_when_reset_is_past() -> None:
    async with client_for(FakeRateLimiter(reset_at=1.0)) as client:
        for _ in range(3):
            response = await client.get("/api")

    assert response.headers["Retry-After"] == "1"


async def test_authenticated_keys_are_scope_kind_id_not_ip() -> None:
    limiter = FakeRateLimiter()
    async with client_for(limiter) as client:
        await client.get("/api", headers={"X-Client-IP": "9.9.9.9"})
        await client.get("/hook")

    assert [identifier for identifier, _ in limiter.hits] == [
        "api:user:u1",
        "webhook:store:s9",
    ]


async def test_auth_keys_use_forwarded_ip_and_hashed_lowercase_email() -> None:
    limiter = FakeRateLimiter()
    async with client_for(limiter) as client:
        response = await client.post("/signin", headers={"X-Client-IP": "203.0.113.7"})

    assert response.status_code == 200
    identifiers = [identifier for identifier, _ in limiter.hits]
    assert identifiers == [
        "auth:ip:203.0.113.7",
        f"auth:email:{email_digest('ada@example.com')}",
    ]
    assert "ada" not in "".join(identifiers)
    assert all(policy == AUTH_POLICY for _, policy in limiter.hits)


async def test_auth_without_email_only_limits_by_ip() -> None:
    limiter = FakeRateLimiter()
    async with client_for(limiter) as client:
        await client.post("/reset", headers={"X-Client-IP": "2001:db8::1"})

    assert [identifier for identifier, _ in limiter.hits] == ["auth:ip:2001:db8::1"]


async def test_auth_sixth_attempt_from_one_ip_is_429() -> None:
    statuses = []
    async with client_for(FakeRateLimiter()) as client:
        for _ in range(6):
            response = await client.post("/reset", headers={"X-Client-IP": "1.2.3.4"})
            statuses.append(response.status_code)

    assert statuses == [200] * 5 + [429]


async def test_missing_or_malformed_client_ip_falls_back_to_the_peer() -> None:
    limiter = FakeRateLimiter()
    async with client_for(limiter) as client:
        await client.post("/reset")
        await client.post("/reset", headers={"X-Client-IP": "not-an-ip"})
        await client.post("/reset", headers={"X-Forwarded-For": "5.5.5.5"})

    identifiers = {identifier for identifier, _ in limiter.hits}
    assert len(identifiers) == 1
    assert next(iter(identifiers)).startswith("auth:ip:")
    assert "5.5.5.5" not in next(iter(identifiers))


async def test_auth_fails_closed_with_503_and_retry_after_when_redis_is_down() -> None:
    async with client_for(RaisingRateLimiter()) as client:
        response = await client.post("/signin", headers={"X-Client-IP": "1.1.1.1"})

    assert response.status_code == 503
    assert response.json() == {
        "success": False,
        "error": "Service temporarily unavailable",
    }
    assert response.headers["Retry-After"] == "5"


@pytest.fixture
def fake_sentry(monkeypatch: pytest.MonkeyPatch) -> list[Exception]:
    captured: list[Exception] = []
    monkeypatch.setattr(sentry_module.sentry_sdk, "is_initialized", lambda: True)
    monkeypatch.setattr(sentry_module.sentry_sdk, "capture_exception", captured.append)
    return captured


@pytest.mark.parametrize("path", ["/api", "/hook"])
async def test_api_and_webhook_fail_open_with_warning_and_sentry(
    path: str, caplog: pytest.LogCaptureFixture, fake_sentry: list[Exception]
) -> None:
    caplog.set_level(logging.WARNING, logger="storecart.rate_limit")
    async with client_for(RaisingRateLimiter()) as client:
        response = await client.get(path)

    assert response.status_code == 200
    assert "X-RateLimit-Limit" not in response.headers
    record = next(r for r in caplog.records if r.name == "storecart.rate_limit")
    assert record.levelno == logging.WARNING
    assert record.request_id == response.headers["X-Request-ID"]  # type: ignore[attr-defined]
    assert len(fake_sentry) == 1


async def test_fail_open_skips_sentry_when_it_is_not_initialised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sentry_module.sentry_sdk, "is_initialized", lambda: False)
    monkeypatch.setattr(
        sentry_module.sentry_sdk,
        "capture_exception",
        lambda _exc: pytest.fail("must not capture"),
    )
    async with client_for(RaisingRateLimiter()) as client:
        response = await client.get("/api")

    assert response.status_code == 200


async def test_upstash_seconds_reset_drives_retry_after_and_reset_header() -> None:
    from types import SimpleNamespace

    from tests.core.test_rate_limit import FakeSlidingWindow, limiter_with

    reset = time.time() + 42.2  # Upstash reports epoch seconds, as a float
    fake = FakeSlidingWindow(
        SimpleNamespace(allowed=False, limit=2, remaining=0, reset=reset)
    )
    limiter = limiter_with(fake)
    limiter._limiters[SMALL_OPEN] = limiter._limiters.pop(API_POLICY)
    app = build_app(FakeRateLimiter())
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api")

    assert response.status_code == 429
    assert response.headers["X-RateLimit-Reset"] == str(math.ceil(reset))
    assert 42 <= int(response.headers["Retry-After"]) <= 44
