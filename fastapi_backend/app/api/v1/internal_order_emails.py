"""QStash callbacks that send order emails (KAN-81).

Public routes like the provisioning callbacks: no service key, the ``Upstash-Signature`` JWT is
the credential. It must sign this exact body for this exact URL, so a delivery meant for the
send route cannot be replayed against the failure route. Not in the OpenAPI schema: only
QStash calls them.

* ``POST /internal/order-emails/send``: send one pending outbox row. 200 when it was sent,
  skipped, refused for good, or was not pending; 500 so QStash retries a transient failure.
* ``POST /internal/order-emails/failed``: QStash's failure callback once the retries ran out;
  a still pending row becomes ``failed``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.deps import get_email_sender, get_session_provider
from app.api.v1.internal_provisioning import (
    INVALID_PAYLOAD_MESSAGE,
    Ack,
    non_retryable,
    verified_qstash_body,
)
from app.core.config import settings
from app.core.database import SessionProvider
from app.services.email import EmailSender
from app.services.order_email_job import (
    FAILED_PATH,
    SEND_PATH,
    InvalidPayload,
    SendFailed,
)
from app.services.order_email_runner import (
    OrderEmailRunner,
    SqlOrderEmailDirectory,
    SqlOrderEmailOutbox,
)
from app.services.store_sessions import open_store_session

router = APIRouter(
    prefix="/internal/order-emails", tags=["internal"], include_in_schema=False
)

SEND_FAILED_MESSAGE = "Order email not sent"


def get_order_email_runner(
    provider: Annotated[SessionProvider, Depends(get_session_provider)],
    sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> OrderEmailRunner:
    return OrderEmailRunner(
        outbox=SqlOrderEmailOutbox(
            lambda store_id: open_store_session(store_id, provider)
        ),
        directory=SqlOrderEmailDirectory(provider.session),
        sender=sender,
        app_url=settings.app_public_url,
    )


Runner = Annotated[OrderEmailRunner, Depends(get_order_email_runner)]


@router.post("/send", response_model=Ack)
async def send_order_email(
    request: Request,
    runner: Runner,
    signature: Annotated[str | None, Header(alias="Upstash-Signature")] = None,
) -> Ack:
    """Send one order email; 500 asks QStash to retry, 4xx does not."""
    body = await verified_qstash_body(request, signature, SEND_PATH)
    try:
        await runner.handle_send(body)
    except InvalidPayload:
        raise non_retryable(400, INVALID_PAYLOAD_MESSAGE) from None
    except SendFailed:
        raise HTTPException(500, SEND_FAILED_MESSAGE) from None
    return Ack()


@router.post("/failed", response_model=Ack)
async def order_email_exhausted(
    request: Request,
    runner: Runner,
    signature: Annotated[str | None, Header(alias="Upstash-Signature")] = None,
) -> Ack:
    """QStash failure callback: an order email ran out of retries, so it is ``failed``."""
    body = await verified_qstash_body(request, signature, FAILED_PATH)
    try:
        await runner.handle_exhausted(body)
    except InvalidPayload:
        raise non_retryable(400, INVALID_PAYLOAD_MESSAGE) from None
    return Ack()
