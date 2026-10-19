"""Stripe Connect webhook (KAN-67): ``account.updated`` and ``account.application.deauthorized``.

A separate endpoint from the Billing webhook with its own signing secret
(``STRIPE_CONNECT_WEBHOOK_SECRET``). Public route: the signature is the credential. Not
in the OpenAPI schema. The event only triggers a re-read of the account from Stripe (see
``ConnectWebhookService``). KAN-69 adds event routing and once-only processing on top.
"""

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.sentry import report_exception
from app.core.stripe_billing import StripeNotConfigured
from app.core.stripe_connect import get_stripe_connect
from app.core.stripe_webhook_body import (
    INVALID_PAYLOAD_MESSAGE,
    NOT_CONFIGURED_MESSAGE,
    PROCESSING_FAILED_MESSAGE,
    read_verified_body,
)
from app.repositories.org_connect import OrgConnectRepository
from app.services.stripe_connect import ConnectWebhookService, MalformedConnectEvent

logger = logging.getLogger("storecart.stripe_connect_webhook")

router = APIRouter(prefix="/webhooks", tags=["webhooks"], include_in_schema=False)


class WebhookAck(BaseModel):
    received: bool = True


def get_connect_webhook_service(session: SessionDep) -> ConnectWebhookService:
    return ConnectWebhookService(
        OrgConnectRepository(session), session, get_stripe_connect
    )


async def _verified_body(request: Request, signature: str | None) -> bytes:
    return await read_verified_body(
        request, signature, settings.STRIPE_CONNECT_WEBHOOK_SECRET
    )


@router.post("/stripe-connect", response_model=WebhookAck)
async def stripe_connect_webhook(
    request: Request,
    service: Annotated[ConnectWebhookService, Depends(get_connect_webhook_service)],
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
) -> WebhookAck:
    """200 once handled or ignored; 5xx makes Stripe retry."""
    body = await _verified_body(request, stripe_signature)
    try:
        event: Any = json.loads(body)
    except ValueError:
        raise HTTPException(400, INVALID_PAYLOAD_MESSAGE) from None
    if not isinstance(event, dict):
        raise HTTPException(400, INVALID_PAYLOAD_MESSAGE)
    try:
        await service.handle(event)
    except MalformedConnectEvent:
        raise HTTPException(400, INVALID_PAYLOAD_MESSAGE) from None
    except StripeNotConfigured:
        # Retryable: the event is not lost while the operator sets STRIPE_SECRET_KEY.
        raise HTTPException(503, NOT_CONFIGURED_MESSAGE) from None
    except Exception as exc:  # noqa: BLE001 - any failure must become a retryable 500
        # Type only: a database error's text can carry statement parameters.
        logger.error("stripe connect webhook handler failed: %s", type(exc).__name__)
        report_exception(exc)
        raise HTTPException(500, PROCESSING_FAILED_MESSAGE) from None
    return WebhookAck()
