"""The transactional email seam (KAN-62): Resend over httpx, and the disabled sender."""

import json
import logging

import httpx
import pytest
from pydantic import SecretStr

from app.api import deps
from app.services.email import (
    RESEND_API_URL,
    DisabledEmailSender,
    EmailDeliveryFailed,
    EmailDisabled,
    EmailMessage,
    ResendEmailSender,
)

API_KEY = "re_test_only_placeholder_key"
LINK = "https://app.example.com/invite/secret-token-value"
MESSAGE = EmailMessage(
    to="new@example.com",
    subject="Join us",
    text=f"Accept: {LINK}",
    html=f'<a href="{LINK}">Accept</a>',
    kind="invitation",
)


def sender_with(handler) -> ResendEmailSender:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ResendEmailSender(API_KEY, "StoreCart <team@example.com>", client=client)


async def test_resend_posts_the_message_with_the_key():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "email_1"})

    await sender_with(handler).send(MESSAGE)

    [request] = seen
    assert str(request.url) == RESEND_API_URL
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    assert json.loads(request.content) == {
        "from": "StoreCart <team@example.com>",
        "to": ["new@example.com"],
        "subject": "Join us",
        "text": MESSAGE.text,
        "html": MESSAGE.html,
    }


async def test_resend_rejection_raises_without_provider_text(caplog):
    caplog.set_level(logging.DEBUG)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "provider-detail"})

    with pytest.raises(EmailDeliveryFailed) as raised:
        await sender_with(handler).send(MESSAGE)

    assert "provider-detail" not in str(raised.value)
    assert "status=422" in caplog.text
    assert LINK not in caplog.text
    assert "new@example.com" not in caplog.text


async def test_resend_network_error_raises(caplog):
    caplog.set_level(logging.DEBUG)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(EmailDeliveryFailed):
        await sender_with(handler).send(MESSAGE)

    assert "ConnectError" in caplog.text
    assert API_KEY not in caplog.text


async def test_resend_without_injected_client_uses_its_own(monkeypatch):
    seen: list[httpx.Request] = []
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda: real(transport=httpx.MockTransport(handler))
    )

    await ResendEmailSender(API_KEY, "team@example.com").send(MESSAGE)

    assert len(seen) == 1


async def test_disabled_sender_logs_only_that_email_is_disabled(caplog):
    caplog.set_level(logging.DEBUG)

    with pytest.raises(EmailDisabled):
        await DisabledEmailSender().send(MESSAGE)

    assert "email disabled" in caplog.text
    assert LINK not in caplog.text
    assert "new@example.com" not in caplog.text


@pytest.fixture
def fresh_sender(monkeypatch):
    monkeypatch.setattr(deps, "_email_sender", None)


def test_sender_is_disabled_without_configuration(monkeypatch, fresh_sender):
    monkeypatch.setattr(deps.settings, "RESEND_API_KEY", None)

    assert isinstance(deps.get_email_sender(), DisabledEmailSender)


@pytest.mark.parametrize(("key", "sender"), [("", "team@example.com"), (API_KEY, " ")])
def test_sender_is_disabled_with_a_blank_value(
    monkeypatch, fresh_sender, caplog, key, sender
):
    monkeypatch.setattr(deps.settings, "RESEND_API_KEY", SecretStr(key))
    monkeypatch.setattr(deps.settings, "EMAIL_FROM", sender)
    monkeypatch.setattr(deps.settings, "ENVIRONMENT", "production")

    assert isinstance(deps.get_email_sender(), DisabledEmailSender)
    assert "emails are disabled" in caplog.text


async def test_resend_request_has_a_short_timeout():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    await sender_with(handler).send(MESSAGE)

    assert seen[0].extensions["timeout"] == {
        "connect": 2.0,
        "read": 5.0,
        "write": 5.0,
        "pool": 5.0,
    }


def test_sender_uses_resend_when_configured(monkeypatch, fresh_sender):
    monkeypatch.setattr(deps.settings, "RESEND_API_KEY", SecretStr(API_KEY))
    monkeypatch.setattr(deps.settings, "EMAIL_FROM", "team@example.com")

    sender = deps.get_email_sender()

    assert isinstance(sender, ResendEmailSender)
    assert deps.get_email_sender() is sender
