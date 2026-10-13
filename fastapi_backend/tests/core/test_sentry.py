from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sentry_sdk.transport import Transport

from app.core.config import Settings
from app.core.logging import request_id_var
from app.core.sentry import (
    FILTERED,
    init_sentry,
    report_exception,
    scrub_event,
    tag_request_id,
)
from app.main import create_app

DSN = "https://publickey@o0.ingest.sentry.io/1"


class RecordingTransport(Transport):
    """In-memory transport: nothing leaves the process."""

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(options)
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Any) -> None:
        for item in envelope.items:
            if item.type == "event":
                self.events.append(item.payload.json)


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "DATABASE_URL": "postgresql+asyncpg://test:test@localhost:5432/test",
        "ENVIRONMENT": "test",
    }
    return Settings(**{**values, **overrides})  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def reset_sentry() -> Iterator[None]:
    yield
    sentry_sdk.get_global_scope().client = None  # type: ignore[assignment]
    sentry_sdk.init()  # disabled client: no DSN


def test_does_not_start_without_a_dsn() -> None:
    started = init_sentry(make_settings(SENTRY_DSN=None))

    assert started is False
    assert sentry_sdk.is_initialized() is False


def test_does_not_start_with_an_empty_dsn() -> None:
    assert init_sentry(make_settings(SENTRY_DSN=SecretStr(""))) is False


def test_starts_with_a_dsn_and_sets_environment_release_and_pii() -> None:
    transport = RecordingTransport()
    settings = make_settings(
        SENTRY_DSN=DSN, VERCEL_ENV="preview", VERCEL_GIT_COMMIT_SHA="abc123"
    )

    started = init_sentry(settings, transport=transport)

    options = sentry_sdk.get_client().options
    assert started is True
    assert options["environment"] == "preview"
    assert options["release"] == "abc123"
    assert options["send_default_pii"] is False


def test_environment_falls_back_to_environment_setting() -> None:
    init_sentry(make_settings(SENTRY_DSN=DSN), transport=RecordingTransport())

    assert sentry_sdk.get_client().options["environment"] == "test"


def test_dsn_is_not_exposed_by_settings_repr() -> None:
    assert DSN not in repr(make_settings(SENTRY_DSN=DSN))


def test_scrub_removes_sensitive_headers_cookies_and_body() -> None:
    event = {
        "request": {
            "headers": {
                "Authorization": "Bearer secret",
                "Cookie": "session=secret",
                "X-Session-Token": "secret",
                "X-Internal-Key": "secret",
                "User-Agent": "pytest",
            },
            "cookies": {"session": "secret"},
            "data": {"password": "secret"},
            "url": "http://test/x",
        }
    }

    scrubbed = scrub_event(event)

    headers = scrubbed["request"]["headers"]
    assert headers["Authorization"] == FILTERED
    assert headers["Cookie"] == FILTERED
    assert headers["X-Session-Token"] == FILTERED
    assert headers["X-Internal-Key"] == FILTERED
    assert headers["User-Agent"] == "pytest"
    assert "data" not in scrubbed["request"]
    assert "cookies" not in scrubbed["request"]
    assert "secret" not in str(scrubbed)


def test_scrub_tolerates_events_without_a_request() -> None:
    assert scrub_event({"message": "x"}) == {"message": "x"}


def test_scrub_adds_the_context_request_id_tag() -> None:
    token = request_id_var.set("req-1")
    try:
        scrubbed = scrub_event({})
    finally:
        request_id_var.reset(token)

    assert scrubbed["tags"] == {"request_id": "req-1"}


def test_helpers_are_noops_when_sentry_is_off() -> None:
    tag_request_id("req-1")
    report_exception(RuntimeError("x"))  # must not raise


async def test_unhandled_exception_is_captured_once_with_context() -> None:
    transport = RecordingTransport()
    init_sentry(make_settings(SENTRY_DSN=DSN), transport=transport)
    app = create_app()

    @app.post("/_test/boom", tags=["t"])
    async def boom() -> None:
        raise RuntimeError("kaboom")

    client = AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )
    async with client:
        response = await client.post(
            "/_test/boom",
            json={"password": "hunter2"},
            headers={"Authorization": "Bearer secret", "X-Session-Token": "tok"},
        )
    sentry_sdk.flush()

    assert response.status_code == 500
    assert response.json() == {"success": False, "error": "Internal server error"}
    assert len(transport.events) == 1
    event = transport.events[0]
    assert event["tags"]["request_id"] == response.headers["X-Request-ID"]
    assert event["request"]["url"].endswith("/_test/boom")
    assert event["exception"]["values"][0]["type"] == "RuntimeError"
    assert "secret" not in str(event)
    assert "hunter2" not in str(event)
    assert "tok" not in event["request"]["headers"].values()
