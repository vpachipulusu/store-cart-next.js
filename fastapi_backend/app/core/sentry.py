"""Sentry error reporting (KAN-35, ADR-003).

Initialised only when SENTRY_DSN is set. Events never carry credentials or request
bodies, and each one is tagged with the request ID from the request-ID middleware.
Unhandled exceptions are reported by the SDK's ASGI middleware when they pass
through the global 500 handler (``app.core.errors``), which does not report them
itself, so there is exactly one event per failure.
"""

from typing import Any

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.transport import Transport

from app.core.config import Settings
from app.core.logging import request_id_var

REQUEST_ID_TAG = "request_id"

# Header names are compared lower-cased. Both ADR-003 credentials are listed, plus
# the standard ones a proxy or client may add.
SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-session-token",
        "x-internal-key",
    }
)
FILTERED = "[Filtered]"


def scrub_event(event: Any, _hint: Any = None) -> Any:
    """``before_send``: drop credentials and bodies, and tag the request ID."""
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("cookies", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                name: FILTERED if name.lower() in SENSITIVE_HEADERS else value
                for name, value in headers.items()
            }
    request_id = request_id_var.get()
    if request_id:
        event.setdefault("tags", {}).setdefault(REQUEST_ID_TAG, request_id)
    return event


def tag_request_id(request_id: str) -> None:
    """Tag the current request's Sentry scope. A no-op when Sentry is off."""
    if sentry_sdk.is_initialized():
        sentry_sdk.get_isolation_scope().set_tag(REQUEST_ID_TAG, request_id)


def report_exception(exc: BaseException) -> None:
    """Report a handled-but-notable exception. A no-op when Sentry is off."""
    if sentry_sdk.is_initialized():
        sentry_sdk.capture_exception(exc)


def init_sentry(
    settings: Settings, transport: type[Transport] | Transport | None = None
) -> bool:
    """Start Sentry when a DSN is configured. Returns whether it was started."""
    if settings.SENTRY_DSN is None:
        return False
    dsn = settings.SENTRY_DSN.get_secret_value()
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=settings.VERCEL_ENV or settings.ENVIRONMENT,
        release=settings.VERCEL_GIT_COMMIT_SHA,
        send_default_pii=False,
        max_request_body_size="never",
        # Frame locals include the raw ASGI scope (all headers), so they stay off.
        include_local_variables=False,
        before_send=scrub_event,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        transport=transport,
    )
    return True
