"""Merchant order management API (KAN-79): list, detail, manual fulfilment and cancelling.

Every route needs the internal service key, a verified session and a membership of the
organisation that owns ``{store_id}`` (``require_merchant``: unknown and foreign stores are
the same 404). The store database that is opened is the one of the store the membership
resolved, never an id taken from the body, so an order id of another store is a plain 404.
Any member may read; fulfilling and cancelling need OWNER or ADMIN and an ACTIVE store.
Cancelling (KAN-256) applies to pending orders only and closes the order's Stripe Checkout
Session first (502 when Stripe cannot be reached, 409 when the shopper already paid).

Errors are curated: 404 for an unknown order, 409 when the order cannot be fulfilled from its
current status (the message does not name the status), 422 for invalid tracking text. Bodies
reject unknown fields. Responses carry ``Cache-Control: no-store``. Money is integer minor
units in the currency stored on the order. ``oversold`` (KAN-72) marks a paid order whose stock
could not cover every line: the shopper was charged, so the merchant fulfils late or refunds.
"""

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.api.auth import require_internal_key
from app.api.deps import SessionDep, get_session_provider
from app.api.merchant import OWNER_ADMIN, require_merchant
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.store_db import STORE_UNAVAILABLE, store_orders_service
from app.api.v1.auth import current_subject
from app.api.v1.checkout import get_stripe_checkout_client
from app.api.v1.organizations import no_store
from app.core.database import SessionProvider
from app.core.errors import ErrorResponse
from app.core.rate_limit import API_POLICY
from app.core.stripe_checkout import StripeCheckout
from app.repositories.merchant import MerchantAccess
from app.repositories.org_connect import OrgConnectRepository
from app.repositories.store_orders import (
    OrderItemRow,
    OrderRow,
    OrderSummaryRow,
    StoreOrdersRepository,
)
from app.services.merchant_order_cancel import (
    MerchantOrderCancelService,
    OrderCancelUnavailable,
    OrderNotCancellable,
    OrderPaymentInProgress,
)
from app.services.merchant_orders import (
    DEFAULT_PAGE_SIZE,
    MAX_OFFSET,
    MAX_PAGE_SIZE,
    OrderDetail,
    StoreOrdersService,
)
from app.services.store_orders import (
    MAX_ID_LENGTH,
    InvalidOrder,
    InvalidOrderTransition,
    OrderError,
    OrderNotFound,
    OrderStatus,
)
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

ReadService = Annotated[StoreOrdersService, Depends(store_orders_service())]
WriteService = Annotated[StoreOrdersService, Depends(store_orders_service(OWNER_ADMIN))]
OrderId = Annotated[
    str, Path(min_length=1, max_length=MAX_ID_LENGTH, pattern=r"^[A-Za-z0-9_-]+$")
]
NO_STORE = {"Cache-Control": "no-store"}


async def cancel_order_service(
    merchant: Annotated[MerchantAccess, Depends(require_merchant(OWNER_ADMIN))],
    provider: Annotated[SessionProvider, Depends(get_session_provider)],
    platform: SessionDep,
    stripe: Annotated[StripeCheckout, Depends(get_stripe_checkout_client)],
) -> AsyncIterator[MerchantOrderCancelService]:
    """The cancel service on the caller's own store database (the one ``require_merchant`` found).

    The connected account is read on the platform database, which is released before the
    store database is opened.
    """
    store_id = merchant.store.id
    connect = await OrgConnectRepository(platform).get(merchant.organization.id)
    await platform.rollback()
    account_id = connect.stripe_connect_account_id if connect else None
    try:
        async with open_store_session(store_id, provider) as session:
            yield MerchantOrderCancelService(
                StoreOrdersService(StoreOrdersRepository(session), session),
                session,
                stripe,
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


CancelService = Annotated[MerchantOrderCancelService, Depends(cancel_order_service)]


class FulfilRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Generous caps bound the request; the service enforces the real limit (100) after trimming.
    tracking_number: Annotated[StrictStr, Field(max_length=1000)]
    carrier: Annotated[StrictStr, Field(max_length=1000)] | None = None


class OrderItemData(BaseModel):
    id: str
    product_name: str
    sku: str
    variant_label: str | None
    unit_price_minor: int
    quantity: int
    tax_rate_bps: int
    tax_minor: int


class OrderSummaryData(BaseModel):
    id: str
    status: OrderStatus
    currency: str
    total_minor: int
    item_count: int
    tracking_number: str | None
    carrier: str | None
    fulfilled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    oversold: bool


class OrderData(BaseModel):
    id: str
    status: OrderStatus
    currency: str
    subtotal_minor: int
    tax_minor: int
    total_minor: int
    tracking_number: str | None
    carrier: str | None
    fulfilled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    oversold: bool
    items: list[OrderItemData]


class OrderResponse(BaseModel):
    data: OrderData


class OrderListResponse(BaseModel):
    data: list[OrderSummaryData]
    total: int
    limit: int
    offset: int


def _summary(row: OrderSummaryRow) -> OrderSummaryData:
    return OrderSummaryData(**{**vars(row), "status": OrderStatus(row.status)})


def _item(row: OrderItemRow) -> OrderItemData:
    return OrderItemData(**vars(row))


def _order(order: OrderRow, items: tuple[OrderItemRow, ...]) -> OrderData:
    return OrderData(
        **{**vars(order), "status": OrderStatus(order.status)},
        items=[_item(i) for i in items],
    )


def _response(detail: OrderDetail) -> OrderResponse:
    return OrderResponse(data=_order(detail.order, detail.items))


def http_error(error: OrderError) -> HTTPException:
    """Map an order error to a response with a fixed message."""
    if isinstance(error, OrderNotFound):
        return HTTPException(404, "Order not found", headers=NO_STORE)
    if isinstance(error, InvalidOrderTransition):
        return HTTPException(
            409, "Only a paid order can be fulfilled", headers=NO_STORE
        )
    if isinstance(error, InvalidOrder):
        return HTTPException(422, str(error), headers=NO_STORE)
    return HTTPException(500, "Internal server error", headers=NO_STORE)


def cancel_http_error(error: OrderError) -> HTTPException:
    """Map a cancel error to a response with a fixed message."""
    if isinstance(error, OrderNotFound):
        return HTTPException(404, "Order not found", headers=NO_STORE)
    if isinstance(error, OrderNotCancellable):
        return HTTPException(
            409, "Only a pending order can be cancelled", headers=NO_STORE
        )
    if isinstance(error, OrderPaymentInProgress):
        return HTTPException(
            409, "The order's payment is being processed", headers=NO_STORE
        )
    if isinstance(error, OrderCancelUnavailable):
        return HTTPException(
            502, "The payment page could not be closed. Try again.", headers=NO_STORE
        )
    return HTTPException(500, "Internal server error", headers=NO_STORE)


@router.get("", response_model=OrderListResponse, summary="List orders")
async def list_orders(
    response: Response,
    service: ReadService,
    status: OrderStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET)] = 0,
) -> OrderListResponse:
    """Newest first, optionally filtered by ``status``."""
    no_store(response)
    page = await service.list_orders(status=status, limit=limit, offset=offset)
    return OrderListResponse(
        data=[_summary(row) for row in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{order_id}", response_model=OrderResponse, summary="Read an order")
async def read_order(
    order_id: OrderId, response: Response, service: ReadService
) -> OrderResponse:
    no_store(response)
    try:
        detail = await service.get(order_id)
    except OrderError as error:
        raise http_error(error) from None
    return _response(detail)


@router.post(
    "/{order_id}/fulfil",
    response_model=OrderResponse,
    summary="Fulfil a paid order with a tracking number",
)
async def fulfil_order(
    order_id: OrderId,
    body: FulfilRequest,
    response: Response,
    service: WriteService,
) -> OrderResponse:
    no_store(response)
    try:
        detail = await service.fulfil(order_id, body.tracking_number, body.carrier)
    except OrderError as error:
        raise http_error(error) from None
    return _response(detail)


@router.post(
    "/{order_id}/cancel",
    response_model=OrderResponse,
    summary="Cancel a pending order and close its payment page",
)
async def cancel_order(
    order_id: OrderId,
    response: Response,
    service: CancelService,
) -> OrderResponse:
    no_store(response)
    try:
        detail = await service.cancel(order_id)
    except OrderError as error:
        raise cancel_http_error(error) from None
    return _response(detail)
