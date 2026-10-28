"""QStash callbacks for the store provisioning job (KAN-56).

Public routes (like the Stripe webhook): no service key, the ``Upstash-Signature`` JWT is
the credential. It must sign this exact body for this exact URL, so a delivery meant for
the step route cannot be replayed against the failure route. Not in the OpenAPI schema:
only QStash calls them.

* ``POST /internal/provisioning/step``: run one step. 200 when done or already done, 500
  so QStash retries a transient failure.
* ``POST /internal/provisioning/failed``: QStash's failure callback once a step has
  exhausted its retries; marks the store FAILED.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from app.api.deps import get_session_provider
from app.core.config import settings
from app.core.database import SessionProvider
from app.core.qstash_signature import InvalidQStashSignature, verify_qstash_signature
from app.services.store_provisioning import get_database_provisioner
from app.services.store_provisioning_job import (
    FAILED_PATH,
    STEP_PATH,
    InvalidPayload,
    StepFailed,
    StepRunner,
    get_step_enqueuer,
)

logger = logging.getLogger("storecart.store_provisioning_job")

router = APIRouter(
    prefix="/internal/provisioning", tags=["internal"], include_in_schema=False
)

NON_RETRYABLE_HEADER = "Upstash-NonRetryable-Error"
MAX_BODY_BYTES = 64_000
INVALID_SIGNATURE_MESSAGE = "Invalid signature"
INVALID_PAYLOAD_MESSAGE = "Invalid payload"
PAYLOAD_TOO_LARGE_MESSAGE = "Payload too large"
STEP_FAILED_MESSAGE = "Provisioning step failed"
UNAVAILABLE_MESSAGE = "Service temporarily unavailable"


class Ack(BaseModel):
    received: bool = True


def get_step_runner(
    provider: Annotated[SessionProvider, Depends(get_session_provider)],
) -> StepRunner:
    return StepRunner(
        provider=provider,
        provisioner=lambda: get_database_provisioner(settings),
        enqueuer=get_step_enqueuer(settings),
    )


def _permanent(status_code: int, message: str) -> HTTPException:
    """An error QStash must not retry: the same body would fail the same way."""
    return HTTPException(status_code, message, headers={NON_RETRYABLE_HEADER: "true"})


async def _verified_body(request: Request, token: str | None, path: str) -> bytes:
    base_url = settings.PROVISIONING_BASE_URL
    keys = settings.qstash_signing_keys
    if not base_url or not keys:
        raise HTTPException(503, UNAVAILABLE_MESSAGE)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _permanent(413, PAYLOAD_TOO_LARGE_MESSAGE)
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_BODY_BYTES:
            raise _permanent(413, PAYLOAD_TOO_LARGE_MESSAGE)
        chunks.append(chunk)
    body = b"".join(chunks)
    expected_url = f"{base_url.rstrip('/')}{path}"
    try:
        verify_qstash_signature(body, token, expected_url, keys)
    except InvalidQStashSignature as exc:
        # Names the failed check (KAN-255); URLs are not secret, the token never logged.
        if exc.reason == "subject":
            logger.warning(
                "qstash signature rejected: reason=subject claimed=%s expected=%s",
                exc.claimed_url,
                expected_url,
            )
        else:
            logger.warning("qstash signature rejected: reason=%s", exc.reason)
        raise HTTPException(401, INVALID_SIGNATURE_MESSAGE) from None
    return body


# The same signature check guards the other QStash callbacks (the cart purge schedule, KAN-252,
# and the order emails, KAN-81), which also answer with the same non-retryable errors.
verified_qstash_body = _verified_body
non_retryable = _permanent


@router.post("/step", response_model=Ack)
async def run_step(
    request: Request,
    runner: Annotated[StepRunner, Depends(get_step_runner)],
    signature: Annotated[str | None, Header(alias="Upstash-Signature")] = None,
) -> Ack:
    """Run one provisioning step; 500 asks QStash to retry, 4xx does not."""
    body = await _verified_body(request, signature, STEP_PATH)
    try:
        await runner.handle_step(body)
    except InvalidPayload:
        raise _permanent(400, INVALID_PAYLOAD_MESSAGE) from None
    except StepFailed:
        raise HTTPException(500, STEP_FAILED_MESSAGE) from None
    return Ack()


@router.post("/failed", response_model=Ack)
async def step_exhausted(
    request: Request,
    runner: Annotated[StepRunner, Depends(get_step_runner)],
    signature: Annotated[str | None, Header(alias="Upstash-Signature")] = None,
) -> Ack:
    """QStash failure callback: a step ran out of retries, so the store is FAILED."""
    body = await _verified_body(request, signature, FAILED_PATH)
    try:
        await runner.handle_exhausted(body)
    except InvalidPayload:
        raise _permanent(400, INVALID_PAYLOAD_MESSAGE) from None
    return Ack()
