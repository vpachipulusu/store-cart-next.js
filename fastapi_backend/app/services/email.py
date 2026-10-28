"""Transactional email (KAN-62, ADR-009): a small sender seam over the Resend HTTP API.

Services depend on the ``EmailSender`` protocol; ``app/api/deps.py`` picks the concrete
sender. Without ``RESEND_API_KEY`` and ``EMAIL_FROM`` the sender is ``DisabledEmailSender``,
which logs that email is disabled and raises ``EmailDisabled``, so callers never report an
unsent message as sent. Neither sender ever logs a recipient, a subject or
a body: bodies carry single-use links. Failures raise ``EmailDeliveryFailed`` with no
provider text; ``EmailRejected`` when the provider refused the request in a way a retry
cannot fix (KAN-81). A message may carry an ``idempotency_key`` (Resend's
``Idempotency-Key`` header), so a retried send is delivered once.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

logger = logging.getLogger("storecart.email")

RESEND_API_URL = "https://api.resend.com/emails"
# Connect fast or give up; callers also bound the whole send (invitations: 5 s).
REQUEST_TIMEOUT = httpx.Timeout(5.0, connect=2.0)
# 4xx answers that a later retry may still turn into a success (timeout, idempotency
# conflict while the first request runs, rate limit); every other 4xx is final.
RETRYABLE_CLIENT_ERRORS = frozenset({408, 409, 429})


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str
    # Short, non-sensitive label for logs (for example "invitation").
    kind: str
    idempotency_key: str | None = None


class EmailDeliveryFailed(Exception):
    """The provider did not accept the message. Carries no provider text."""


class EmailDisabled(EmailDeliveryFailed):
    """Email is not configured, so nothing was sent (callers report "not sent")."""


class EmailRejected(EmailDeliveryFailed):
    """The provider refused the message for good (a 4xx a retry cannot fix)."""


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None:
        """Send ``message`` or raise ``EmailDeliveryFailed``."""


class DisabledEmailSender:
    """Email not configured: nothing is sent and nothing about the message is logged."""

    async def send(self, message: EmailMessage) -> None:
        logger.info("email disabled: kind=%s not sent", message.kind)
        raise EmailDisabled


class ResendEmailSender:
    def __init__(
        self,
        api_key: str,
        from_address: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._from = from_address
        self._client = client

    async def _post(self, client: httpx.AsyncClient, message: EmailMessage) -> int:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        if message.idempotency_key:
            headers["Idempotency-Key"] = message.idempotency_key
        response = await client.post(
            RESEND_API_URL,
            headers=headers,
            json={
                "from": self._from,
                "to": [message.to],
                "subject": message.subject,
                "text": message.text,
                "html": message.html,
            },
            timeout=REQUEST_TIMEOUT,
        )
        return response.status_code

    async def send(self, message: EmailMessage) -> None:
        try:
            if self._client is not None:
                status = await self._post(self._client, message)
            else:
                async with httpx.AsyncClient() as client:
                    status = await self._post(client, message)
        except httpx.HTTPError as exc:
            logger.warning(
                "email send failed: kind=%s error=%s", message.kind, type(exc).__name__
            )
            raise EmailDeliveryFailed from None
        if not 200 <= status < 300:
            logger.warning("email rejected: kind=%s status=%s", message.kind, status)
            if 400 <= status < 500 and status not in RETRYABLE_CLIENT_ERRORS:
                raise EmailRejected
            raise EmailDeliveryFailed
