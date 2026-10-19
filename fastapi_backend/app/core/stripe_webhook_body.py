"""Read and authenticate a Stripe webhook body (KAN-44, KAN-67).

Shared by the Billing and Connect webhook routes, which differ only in their signing secret.
The body is read as raw bytes (the signature covers them) under a size cap, then checked with
``verify_signature``. Nothing here logs the header, body or secret.
"""

import logging

from fastapi import HTTPException, Request
from pydantic import SecretStr

from app.core.stripe_signature import InvalidSignature, verify_signature

logger = logging.getLogger("storecart.stripe_webhook")

MAX_BODY_BYTES = 1_000_000
INVALID_SIGNATURE_MESSAGE = "Invalid signature"
INVALID_PAYLOAD_MESSAGE = "Invalid payload"
PAYLOAD_TOO_LARGE_MESSAGE = "Payload too large"
PROCESSING_FAILED_MESSAGE = "Webhook processing failed"
NOT_CONFIGURED_MESSAGE = "Service temporarily unavailable"


async def read_verified_body(
    request: Request, signature: str | None, secret: SecretStr | None
) -> bytes:
    """The raw body once its Stripe signature checks out against ``secret`` (503 if unset)."""
    if secret is None:
        raise HTTPException(503, NOT_CONFIGURED_MESSAGE)
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
        # Header presence only (never its value): a missing header and a wrong secret need different fixes.
        logger.warning(
            "stripe webhook signature rejected: header=%s",
            "present" if signature else "missing",
        )
        raise HTTPException(400, INVALID_SIGNATURE_MESSAGE) from None
    return body
