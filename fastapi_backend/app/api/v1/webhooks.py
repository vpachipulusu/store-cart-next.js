import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, SecretStr

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.plans import PlanKey
from app.core.sentry import report_exception
from app.core.stripe_signature import InvalidSignature, verify_signature
from app.repositories.billing import (
    OrganizationBillingRepository,
    StripeEventRepository,
)
from app.services.stripe_webhook import MalformedEvent, StripeWebhookService

logger = logging.getLogger("storecart.stripe_webhook")

# Public route (ADR-003 section 5): no service key, the Stripe signature is the credential.
# Not in the OpenAPI schema: Stripe calls it, the generated client never does.
router = APIRouter(prefix="/webhooks", tags=["webhooks"], include_in_schema=False)

MAX_BODY_BYTES = 1_000_000
INVALID_SIGNATURE_MESSAGE = "Invalid signature"
INVALID_PAYLOAD_MESSAGE = "Invalid payload"
PAYLOAD_TOO_LARGE_MESSAGE = "Payload too large"
PROCESSING_FAILED_MESSAGE = "Webhook processing failed"


class WebhookAck(BaseModel):
    received: bool = True


def price_catalogue() -> dict[str, PlanKey]:
    """Stripe price id to plan, from settings; unset prices are left out."""
    configured = {
        settings.STRIPE_PRICE_ID_PRO_MONTHLY: PlanKey.PRO,
        settings.STRIPE_PRICE_ID_PRO_YEARLY: PlanKey.PRO,
        settings.STRIPE_PRICE_ID_ENTERPRISE_MONTHLY: PlanKey.ENTERPRISE,
        settings.STRIPE_PRICE_ID_ENTERPRISE_YEARLY: PlanKey.ENTERPRISE,
    }
    return {price: plan for price, plan in configured.items() if price}


def get_stripe_webhook_service(session: SessionDep) -> StripeWebhookService:
    return StripeWebhookService(
        StripeEventRepository(session),
        OrganizationBillingRepository(session),
        session,
        price_catalogue(),
    )


async def _verified_body(request: Request, signature: str | None) -> bytes:
    return await read_verified_body(request, signature, settings.STRIPE_WEBHOOK_SECRET)


async def read_verified_body(
    request: Request, signature: str | None, secret: SecretStr | None
) -> bytes:
    """The raw body once its Stripe signature checks out against ``secret`` (503 if unset)."""
    if secret is None:
        raise HTTPException(503, "Service temporarily unavailable")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(413, PAYLOAD_TOO_LARGE_MESSAGE)
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_BODY_BYTES:
            raise HTTPException(413, PAYLOAD_TOO_LARGE_MESSAGE)
        chunks.append(chunk)
    body = b"".join(chunks)
    try:
        verify_signature(body, signature, secret.get_secret_value())
    except InvalidSignature:
        logger.warning("stripe webhook signature rejected")
        raise HTTPException(400, INVALID_SIGNATURE_MESSAGE) from None
    return body


@router.post("/stripe", response_model=WebhookAck)
async def stripe_webhook(
    request: Request,
    service: Annotated[StripeWebhookService, Depends(get_stripe_webhook_service)],
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
) -> WebhookAck:
    """Receive a Stripe Billing event: 200 once handled, duplicate or ignored; 5xx makes Stripe retry."""
    body = await _verified_body(request, stripe_signature)
    try:
        event: Any = json.loads(body)
    except ValueError:
        raise HTTPException(400, INVALID_PAYLOAD_MESSAGE) from None
    if not isinstance(event, dict):
        raise HTTPException(400, INVALID_PAYLOAD_MESSAGE)
    try:
        await service.handle(event)
    except MalformedEvent:
        raise HTTPException(400, INVALID_PAYLOAD_MESSAGE) from None
    except Exception as exc:  # noqa: BLE001 - any failure must become a retryable 500
        # Type only: a database error's text can carry statement parameters.
        logger.error("stripe webhook handler failed: %s", type(exc).__name__)
        report_exception(exc)
        raise HTTPException(500, PROCESSING_FAILED_MESSAGE) from None
    return WebhookAck()
