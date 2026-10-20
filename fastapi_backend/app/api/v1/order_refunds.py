"""Merchant refunds of paid orders (KAN-80).

``POST /v1/stores/{store_id}/orders/{order_id}/refunds`` refunds a paid or fulfilled order
through the merchant's connected account: in full (no ``items``) or by lines. Same access as
fulfilling: OWNER or ADMIN of the store's organisation, ACTIVE store (``require_merchant``;
unknown and foreign stores are the same 404), the internal key and the per-subject rate limit.
The store database that is opened is the one the membership resolved.

``restock`` (default false) is the merchant's choice per refund: only when true are the
refunded quantities returned to variant stock, once, when Stripe confirms the refund, and never
more than the order took (see ``app/services/store_refunds.py``).

The refund is ``pending`` until Stripe confirms it; the response is the order with its refunds,
so a pending refund is visible and the Connect webhook settles it (order and refund status).
Errors are curated: 404 unknown order, 409 not refundable, more than remains, or refused by
Stripe, 422 invalid lines, 502 when Stripe cannot be reached (the refund may still happen;
do not repeat the request, read the order), 503 when Stripe is not configured or the store
database is unavailable. Bodies reject unknown fields. Responses carry ``Cache-Control:
no-store``.
"""

import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from app.api.auth import require_internal_key
from app.api.deps import SessionDep, get_session_provider
from app.api.merchant import OWNER_ADMIN, require_merchant
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.store_db import NO_STORE_HEADERS, STORE_UNAVAILABLE
from app.api.v1.auth import current_subject
from app.api.v1.orders import NO_STORE, OrderId, OrderResponse, order_response
from app.api.v1.organizations import no_store
from app.core.database import SessionProvider
from app.core.errors import ErrorResponse
from app.core.rate_limit import API_POLICY
from app.core.stripe_billing import StripeNotConfigured
from app.core.stripe_refunds import StripeRefunds, get_stripe_refunds
from app.repositories.merchant import MerchantAccess
from app.repositories.org_connect import OrgConnectRepository
from app.repositories.store_orders import StoreOrdersRepository
from app.services.merchant_order_refund import (
    MerchantOrderRefundService,
    RefundNotConnected,
    RefundRefused,
    RefundUnavailable,
)
from app.services.merchant_orders import StoreOrdersService
from app.services.store_orders import (
    MAX_ID_LENGTH,
    MAX_LINES,
    MAX_QUANTITY,
    InvalidOrder,
    OrderError,
    OrderNotFound,
)
from app.services.store_refunds import RefundLineInput, RefundNotAllowed
from app.services.store_sessions import StoreSessionError, open_store_session

router = APIRouter(
    prefix="/v1/stores/{store_id}/orders",
    tags=["orders"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_subject(API_POLICY, current_subject)),
    ],
    responses={
        **RATE_LIMIT_FAIL_CLOSED_RESPONSES,
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)

logger = logging.getLogger(__name__)

NOT_CONFIGURED = "Payments are not configured"


class RefundItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_item_id: Annotated[StrictStr, Field(min_length=1, max_length=MAX_ID_LENGTH)]
    quantity: Annotated[StrictInt, Field(ge=1, le=MAX_QUANTITY)]


class RefundRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Omitted: refund everything that remains (including shipping).
    items: (
        Annotated[list[RefundItemRequest], Field(min_length=1, max_length=MAX_LINES)]
        | None
    ) = None
    # Return the refunded quantities to stock (once, when the refund succeeds).
    restock: StrictBool = False


def get_stripe_refunds_client() -> StripeRefunds:
    try:
        return get_stripe_refunds()
    except StripeNotConfigured:
        raise HTTPException(503, NOT_CONFIGURED, headers=NO_STORE_HEADERS) from None


async def refund_order_service(
    merchant: Annotated[MerchantAccess, Depends(require_merchant(OWNER_ADMIN))],
    provider: Annotated[SessionProvider, Depends(get_session_provider)],
    platform: SessionDep,
    stripe: Annotated[StripeRefunds, Depends(get_stripe_refunds_client)],
) -> AsyncIterator[MerchantOrderRefundService]:
    """The refund service on the caller's own store database (the one ``require_merchant`` found).

    The connected account is read on the platform database, which is released before the
    store database is opened.
    """
    store_id = merchant.store.id
    connect = await OrgConnectRepository(platform).get(merchant.organization.id)
    await platform.rollback()
    account_id = connect.stripe_connect_account_id if connect else None
    try:
        async with open_store_session(store_id, provider) as session:
            yield MerchantOrderRefundService(
                StoreOrdersService(StoreOrdersRepository(session), session),
                session,
                stripe,
                store_id,
                account_id,
            )
    except StoreSessionError as error:
        reason = type(error).__name__
        logger.error(
            "store database unavailable: %s",
            reason,
            extra={"store_id": store_id, "reason": reason},
        )
        raise HTTPException(503, STORE_UNAVAILABLE) from None


RefundService = Annotated[MerchantOrderRefundService, Depends(refund_order_service)]


def refund_http_error(error: OrderError) -> HTTPException:
    """Map a refund error to a response with a fixed message."""
    if isinstance(error, OrderNotFound):
        return HTTPException(404, "Order not found", headers=NO_STORE)
    if isinstance(error, RefundNotAllowed):
        return HTTPException(409, str(error), headers=NO_STORE)
    if isinstance(error, RefundNotConnected):
        return HTTPException(
            409, "Connect your payment account to refund orders", headers=NO_STORE
        )
    if isinstance(error, RefundRefused):
        return HTTPException(
            409, "The payment provider could not refund this payment", headers=NO_STORE
        )
    if isinstance(error, InvalidOrder):
        return HTTPException(422, str(error), headers=NO_STORE)
    if isinstance(error, RefundUnavailable):
        return HTTPException(
            502,
            "The refund could not be confirmed. Check the order before trying again.",
            headers=NO_STORE,
        )
    return HTTPException(500, "Internal server error", headers=NO_STORE)


@router.post(
    "/{order_id}/refunds",
    response_model=OrderResponse,
    summary="Refund a paid order, in full or by lines",
    responses={
        409: {
            "description": "Not refundable, more than remains, no connected payment "
            "account, or refused by the payment provider. Nothing was refunded."
        },
        422: {"description": "Invalid lines or quantities."},
        502: {
            "description": "The outcome is unknown: the refund may still happen. Do not "
            "repeat the request; read the order and its `refunds`."
        },
    },
)
async def refund_order(
    order_id: OrderId,
    body: RefundRequestBody,
    response: Response,
    service: RefundService,
) -> OrderResponse:
    no_store(response)
    lines = (
        None
        if body.items is None
        else [RefundLineInput(i.order_item_id, i.quantity) for i in body.items]
    )
    try:
        detail = await service.refund(order_id, lines, restock=body.restock)
    except OrderError as error:
        raise refund_http_error(error) from None
    return order_response(detail)
