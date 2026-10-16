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

import base64
import binascii
import json
import logging
from typing import Annotated, Any

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
    StepFailed,
    StepRunner,
    get_step_enqueuer,
    mark_failed,
    parse_step_payload,
)

logger = logging.getLogger("storecart.store_provisioning_job")

router = APIRouter(
    prefix="/internal/provisioning", tags=["internal"], include_in_schema=False
)

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


async def _verified_body(request: Request, token: str | None, path: str) -> bytes:
    base_url = settings.PROVISIONING_BASE_URL
    keys = settings.qstash_signing_keys
    if not base_url or not keys:
        raise HTTPException(503, UNAVAILABLE_MESSAGE)
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
        verify_qstash_signature(body, token, f"{base_url.rstrip('/')}{path}", keys)
    except InvalidQStashSignature:
        logger.warning("qstash signature rejected")
        raise HTTPException(401, INVALID_SIGNATURE_MESSAGE) from None
    return body


def _json(raw: bytes | str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        raise HTTPException(400, INVALID_PAYLOAD_MESSAGE) from None


def _source_body(callback: Any) -> Any:
    """The original step body QStash echoes (base64) in a failure callback."""
    encoded = callback.get("sourceBody") if isinstance(callback, dict) else None
    if not isinstance(encoded, str):
        raise HTTPException(400, INVALID_PAYLOAD_MESSAGE)
    try:
        return _json(base64.b64decode(encoded, validate=True))
    except (binascii.Error, ValueError):
        raise HTTPException(400, INVALID_PAYLOAD_MESSAGE) from None


@router.post("/step", response_model=Ack)
async def run_step(
    request: Request,
    runner: Annotated[StepRunner, Depends(get_step_runner)],
    signature: Annotated[str | None, Header(alias="Upstash-Signature")] = None,
) -> Ack:
    """Run one provisioning step; 500 asks QStash to retry."""
    body = await _verified_body(request, signature, STEP_PATH)
    parsed = parse_step_payload(_json(body))
    if parsed is None:
        raise HTTPException(400, INVALID_PAYLOAD_MESSAGE)
    step, store_id = parsed
    try:
        await runner.run(step, store_id)
    except StepFailed:
        raise HTTPException(500, STEP_FAILED_MESSAGE) from None
    return Ack()


@router.post("/failed", response_model=Ack)
async def step_exhausted(
    request: Request,
    provider: Annotated[SessionProvider, Depends(get_session_provider)],
    signature: Annotated[str | None, Header(alias="Upstash-Signature")] = None,
) -> Ack:
    """QStash failure callback: a step ran out of retries, so the store is FAILED."""
    body = await _verified_body(request, signature, FAILED_PATH)
    parsed = parse_step_payload(_source_body(_json(body)))
    if parsed is None:
        raise HTTPException(400, INVALID_PAYLOAD_MESSAGE)
    await mark_failed(provider, parsed[1])
    return Ack()
