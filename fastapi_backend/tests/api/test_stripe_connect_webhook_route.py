"""Connect webhook route with a fake service: signature, size and error handling (KAN-67)."""

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.api.deps import get_session_provider
from app.api.v1.webhooks import MAX_BODY_BYTES
from app.api.v1.webhooks_connect import get_connect_webhook_service
from app.core.config import settings
from app.core.stripe_signature import compute_signature
from app.main import create_app
from app.services.stripe_connect import MalformedConnectEvent, WebhookOutcome
from tests.fakes import FakeSession, FakeSessionProvider

SECRET = "whsec_connect_test_only_not_real"
PATH = "/webhooks/stripe-connect"
BODY = json.dumps({"id": "evt_1", "type": "account.updated", "created": 1}).encode()


class FakeService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.events: list[dict[str, Any]] = []

    async def handle(self, event: dict[str, Any]) -> WebhookOutcome:
        if self.error is not None:
            raise self.error
        self.events.append(event)
        return WebhookOutcome.PROCESSED


def signed(body: bytes, secret: str = SECRET, timestamp: int | None = None):
    stamp = int(time.time()) if timestamp is None else timestamp
    return {
        "Stripe-Signature": f"t={stamp},v1={compute_signature(secret, stamp, body)}"
    }


@pytest.fixture
def service() -> FakeService:
    return FakeService()


@pytest.fixture
async def client(
    monkeypatch: pytest.MonkeyPatch, service: FakeService
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(settings, "STRIPE_CONNECT_WEBHOOK_SECRET", SecretStr(SECRET))
    app = create_app()
    app.dependency_overrides[get_connect_webhook_service] = lambda: service
    app.dependency_overrides[get_session_provider] = lambda: FakeSessionProvider(
        FakeSession()
    )
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


async def test_valid_signature_is_acknowledged_and_handled(client, service):
    response = await client.post(PATH, content=BODY, headers=signed(BODY))

    assert response.status_code == 200
    assert response.json() == {"received": True}
    assert [e["id"] for e in service.events] == ["evt_1"]


async def test_the_billing_secret_does_not_sign_connect_events(
    client, service, monkeypatch
):
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", SecretStr("whsec_billing"))

    response = await client.post(
        PATH, content=BODY, headers=signed(BODY, "whsec_billing")
    )

    assert response.status_code == 400 and service.events == []


@pytest.mark.parametrize("variant", ["bad", "missing", "tampered", "stale"])
async def test_unsigned_or_wrongly_signed_requests_get_a_generic_400(
    client, service, variant
):
    headers = {
        "bad": signed(BODY, "whsec_wrong"),
        "missing": {},
        "tampered": signed(BODY),
        "stale": signed(BODY, timestamp=int(time.time()) - 3600),
    }[variant]
    content = BODY + b" " if variant == "tampered" else BODY

    response = await client.post(PATH, content=content, headers=headers)

    assert response.status_code == 400
    assert response.json() == {"success": False, "error": "Invalid signature"}
    assert service.events == []


async def test_returns_503_when_the_secret_is_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_CONNECT_WEBHOOK_SECRET", None)

    response = await client.post(PATH, content=BODY, headers=signed(BODY))

    assert response.status_code == 503


async def test_oversized_bodies_are_rejected_with_413(client, service):
    big = b"x" * (MAX_BODY_BYTES + 1)

    response = await client.post(PATH, content=big, headers=signed(big))

    assert response.status_code == 413 and service.events == []


@pytest.mark.parametrize("payload", [b"not json", b"[1, 2]"])
async def test_signed_non_object_json_is_400(client, payload):
    response = await client.post(PATH, content=payload, headers=signed(payload))

    assert response.status_code == 400
    assert response.json() == {"success": False, "error": "Invalid payload"}


async def test_malformed_event_is_400(client, service):
    service.error = MalformedConnectEvent()

    response = await client.post(PATH, content=BODY, headers=signed(BODY))

    assert response.status_code == 400
    assert response.json()["error"] == "Invalid payload"


async def test_unexpected_failure_is_a_generic_retryable_500(client, service, caplog):
    service.error = RuntimeError("password=hunter2 in sql")

    response = await client.post(PATH, content=BODY, headers=signed(BODY))

    assert response.status_code == 500
    assert response.json() == {"success": False, "error": "Webhook processing failed"}
    assert "hunter2" not in caplog.text
