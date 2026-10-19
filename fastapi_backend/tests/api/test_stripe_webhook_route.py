"""Route behaviour with a fake service: no database (the real-database run is the e2e test)."""

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.api.deps import get_session_provider
from app.api.v1.webhooks import (
    get_stripe_webhook_service,
    price_catalogue,
)
from app.core.config import settings
from app.core.plans import PlanKey
from app.core.stripe_signature import compute_signature
from app.core.stripe_webhook_body import MAX_BODY_BYTES
from app.main import create_app
from app.services.stripe_webhook import MalformedEvent, WebhookOutcome
from tests.fakes import FakeSession, FakeSessionProvider

SECRET = "whsec_test_only_not_a_real_secret"


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
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", SecretStr(SECRET))
    app = create_app()
    app.dependency_overrides[get_stripe_webhook_service] = lambda: service
    app.dependency_overrides[get_session_provider] = lambda: FakeSessionProvider(
        FakeSession()
    )
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


BODY = json.dumps({"id": "evt_1", "type": "x", "created": 1}).encode()


async def test_valid_signature_is_acknowledged_and_handled(client, service):
    response = await client.post("/webhooks/stripe", content=BODY, headers=signed(BODY))

    assert response.status_code == 200
    assert response.json() == {"received": True}
    assert [e["id"] for e in service.events] == ["evt_1"]


async def test_bad_signature_returns_400_and_processes_nothing(client, service):
    response = await client.post(
        "/webhooks/stripe", content=BODY, headers=signed(BODY, "whsec_wrong")
    )

    assert response.status_code == 400
    assert response.json() == {"success": False, "error": "Invalid signature"}
    assert service.events == []


async def test_missing_signature_header_returns_400(client, service):
    response = await client.post("/webhooks/stripe", content=BODY)

    assert response.status_code == 400 and service.events == []


async def test_rejected_signature_log_says_whether_the_header_was_present(
    client, caplog
):
    with caplog.at_level(logging.WARNING, logger="storecart.stripe_webhook"):
        await client.post(
            "/webhooks/stripe", content=BODY, headers=signed(BODY, "whsec_wrong")
        )
        await client.post("/webhooks/stripe", content=BODY)

    messages = [record.getMessage() for record in caplog.records]
    assert messages == [
        "stripe webhook signature rejected: header=present",
        "stripe webhook signature rejected: header=missing",
    ]
    assert "whsec_wrong" not in caplog.text


async def test_signature_is_checked_against_the_raw_bytes(client, service):
    headers = signed(BODY)

    response = await client.post(
        "/webhooks/stripe", content=BODY + b" ", headers=headers
    )

    assert response.status_code == 400 and service.events == []


async def test_stale_timestamp_is_rejected(client, service):
    old = int(time.time()) - 3600

    response = await client.post(
        "/webhooks/stripe", content=BODY, headers=signed(BODY, timestamp=old)
    )

    assert response.status_code == 400 and service.events == []


async def test_returns_503_when_the_secret_is_not_configured(
    client, service, monkeypatch
):
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", None)

    response = await client.post("/webhooks/stripe", content=BODY, headers=signed(BODY))

    assert response.status_code == 503 and service.events == []


@pytest.mark.parametrize("raw", [b"not json", b"[1, 2]", b'"text"'])
async def test_signed_but_unparseable_payload_returns_400(client, service, raw):
    response = await client.post("/webhooks/stripe", content=raw, headers=signed(raw))

    assert response.status_code == 400
    assert response.json()["error"] == "Invalid payload"
    assert service.events == []


async def test_malformed_event_returns_400(client, service):
    service.error = MalformedEvent()

    response = await client.post("/webhooks/stripe", content=BODY, headers=signed(BODY))

    assert response.status_code == 400
    assert response.json()["error"] == "Invalid payload"


async def test_handler_failure_returns_a_generic_500_so_stripe_retries(client, service):
    service.error = RuntimeError("secret detail postgresql://user:pw@host/db")

    response = await client.post("/webhooks/stripe", content=BODY, headers=signed(BODY))

    assert response.status_code == 500
    assert response.json() == {"success": False, "error": "Webhook processing failed"}
    assert "pw@host" not in response.text


async def test_oversized_body_is_rejected_before_verification(client, service):
    big = b"x" * (MAX_BODY_BYTES + 1)

    response = await client.post("/webhooks/stripe", content=big, headers=signed(big))

    assert response.status_code == 413 and service.events == []


async def test_oversized_streamed_body_is_rejected_without_a_content_length(
    client, service
):
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(3):
            yield b"x" * (MAX_BODY_BYTES // 2)

    response = await client.post(
        "/webhooks/stripe", content=chunks(), headers=signed(BODY)
    )

    assert response.status_code == 413 and service.events == []


async def test_route_is_not_in_the_openapi_schema(client):
    schema = (await client.get("/openapi.json")).json()

    assert not any("webhooks" in path for path in schema["paths"])


def test_price_catalogue_maps_configured_prices_and_skips_unset(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID_PRO_MONTHLY", "price_pm")
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID_PRO_YEARLY", None)
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID_ENTERPRISE_MONTHLY", "price_em")
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID_ENTERPRISE_YEARLY", "price_ey")

    assert price_catalogue() == {
        "price_pm": PlanKey.PRO,
        "price_em": PlanKey.ENTERPRISE,
        "price_ey": PlanKey.ENTERPRISE,
    }
