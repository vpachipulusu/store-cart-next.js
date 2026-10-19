"""Stripe Connect webhook (KAN-67): ``account.updated`` only.

A separate endpoint from the Billing webhook with its own signing secret
(``STRIPE_CONNECT_WEBHOOK_SECRET``). Public route: the signature is the credential. Not
in the OpenAPI schema. KAN-69 adds event routing and once-only processing; until then
the update is idempotent by construction (see ``OrgConnectRepository.apply_account_update``).
"""

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from app.api.deps import SessionDep
from app.api.v1.webhooks import (
    INVALID_PAYLOAD_MESSAGE,
    PROCESSING_FAILED_MESSAGE,
    read_verified_body,
)
from app.core.config import settings
from app.core.sentry import report_exception
from app.repositories.org_connect import OrgConnectRepository
from app.services.stripe_connect import ConnectWebhookService, MalformedConnectEvent

logger = logging.getLogger("storecart.stripe_connect_webhook")

router = APIRouter(prefix="/webhooks", tags=["webhooks"], include_in_schema=False)


class WebhookAck(BaseModel):
    received: bool = True


def get_connect_webhook_service(session: SessionDep) -> ConnectWebhookService:
    return ConnectWebhookService(OrgConnectRepository(session), session)


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
    except Exception as exc:  # noqa: BLE001 - any failure must become a retryable 500
        # Type only: a database error's text can carry statement parameters.
        logger.error("stripe connect webhook handler failed: %s", type(exc).__name__)
        report_exception(exc)
        raise HTTPException(500, PROCESSING_FAILED_MESSAGE) from None
    return WebhookAck()
