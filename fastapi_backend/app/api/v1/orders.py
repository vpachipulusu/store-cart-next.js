"""Merchant order management API (KAN-79): list, detail and manual fulfilment.

Every route needs the internal service key, a verified session and a membership of the
organisation that owns ``{store_id}`` (``require_merchant``: unknown and foreign stores are
the same 404). The store database that is opened is the one of the store the membership
resolved, never an id taken from the body, so an order id of another store is a plain 404.
Any member may read; fulfilling needs OWNER or ADMIN and an ACTIVE store.

Errors are curated: 404 for an unknown order, 409 when the order cannot be fulfilled from its
current status (the message does not name the status), 422 for invalid tracking text. Bodies
reject unknown fields. Responses carry ``Cache-Control: no-store``. Money is integer minor
units in the currency stored on the order.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.api.auth import require_internal_key
from app.api.merchant import OWNER_ADMIN
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.store_db import store_orders_service
from app.api.v1.auth import current_subject
from app.api.v1.organizations import no_store
from app.core.errors import ErrorResponse
from app.core.rate_limit import API_POLICY
from app.repositories.store_orders import OrderItemRow, OrderRow, OrderSummaryRow
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
        503: {"model": ErrorResponse},
    },
)

ReadService = Annotated[StoreOrdersService, Depends(store_orders_service())]
WriteService = Annotated[StoreOrdersService, Depends(store_orders_service(OWNER_ADMIN))]
OrderId = Annotated[
    str, Path(min_length=1, max_length=MAX_ID_LENGTH, pattern=r"^[A-Za-z0-9_-]+$")
]
NO_STORE = {"Cache-Control": "no-store"}


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
