"""Public shopper cart (KAN-76): ``/v1/storefront/{slug}/cart``.

Called only by the Next.js server (decision D14), so it needs the internal service key but no
user session. The shopper's cart token travels in the ``X-Cart-Token`` header; Next.js keeps
it in an httpOnly cookie scoped to that store. Every route answers with the whole cart, priced
from the catalogue at that moment (never from anything the client sent): the request names a
variant and a quantity, nothing else.

A write without a live token starts a cart and returns its token once, in ``cart_token``; the
caller must store it. Reads never create a cart and never return a token. The slug must be an
ACTIVE store, otherwise it is the same 404 as the storefront lookup. Responses are
``no-store``.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.api.auth import require_internal_key
from app.api.rate_limit import RATE_LIMIT_RESPONSES, limit_by_client_ip
from app.api.store_db import storefront_cart_service
from app.core.errors import ErrorResponse
from app.core.rate_limit import CART_POLICY
from app.services.store_cart import (
    MAX_QUANTITY,
    CartError,
    CartView,
    ItemUnavailable,
    LineStatus,
    StoreCartService,
)

NO_STORE_HEADERS = {"Cache-Control": "no-store"}
CART_TOKEN_HEADER = "X-Cart-Token"

router = APIRouter(
    prefix="/v1/storefront/{slug}/cart",
    tags=["cart"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_client_ip(CART_POLICY)),
    ],
    responses={
        **RATE_LIMIT_RESPONSES,
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)

CartService = Annotated[StoreCartService, Depends(storefront_cart_service)]
CartToken = Annotated[
    str | None,
    Header(
        alias=CART_TOKEN_HEADER,
        max_length=128,
        description="The shopper's cart token. Missing, unknown or expired reads as an empty cart.",
    ),
]
VariantId = Annotated[str, Path(min_length=1, max_length=100)]


class CartItemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_id: str = Field(min_length=1, max_length=100)
    quantity: StrictInt = Field(ge=1, le=MAX_QUANTITY)


class CartQuantityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: StrictInt = Field(ge=1, le=MAX_QUANTITY)


class CartLineData(BaseModel):
    variant_id: str
    product_id: str
    product_name: str
    product_slug: str
    sku: str
    variant_label: str | None
    unit_price_minor: int
    quantity: int
    line_total_minor: int
    available_stock: int
    status: LineStatus = Field(
        description="`ok`, or why the line is not purchasable and left out of the totals."
    )


class CartData(BaseModel):
    lines: list[CartLineData]
    subtotal_minor: int
    shipping_minor: int
    tax_minor: int
    total_minor: int
    prices_include_tax: bool
    can_checkout: bool = Field(
        description="True when the cart has lines and every line is `ok`."
    )
    cart_token: str | None = Field(
        default=None,
        description="Set only when this request started a new cart. Store it; it is not shown again.",
    )


class CartResponse(BaseModel):
    success: Literal[True] = True
    data: CartData


def _response(view: CartView, response: Response) -> CartResponse:
    response.headers["Cache-Control"] = NO_STORE_HEADERS["Cache-Control"]
    return CartResponse(
        data=CartData(
            lines=[CartLineData(**vars(line)) for line in view.lines],
            subtotal_minor=view.totals.subtotal_minor,
            shipping_minor=view.totals.shipping_minor,
            tax_minor=view.totals.tax_minor,
            total_minor=view.totals.total_minor,
            prices_include_tax=view.totals.prices_include_tax,
            can_checkout=view.can_checkout,
            cart_token=view.new_token,
        )
    )


def _http_error(error: CartError) -> HTTPException:
    status = 404 if isinstance(error, ItemUnavailable) else 409
    return HTTPException(status, str(error), headers=NO_STORE_HEADERS)


@router.get("", response_model=CartResponse, summary="Read the cart, priced now")
async def read_cart(
    response: Response, service: CartService, token: CartToken = None
) -> CartResponse:
    return _response(await service.view(token), response)


@router.post(
    "/items",
    response_model=CartResponse,
    summary="Add a variant to the cart",
    description="Adds to the quantity already in the cart. Starts a cart when the token has none.",
)
async def add_cart_item(
    body: CartItemBody,
    response: Response,
    service: CartService,
    token: CartToken = None,
) -> CartResponse:
    try:
        view = await service.add_item(token, body.variant_id, body.quantity)
    except CartError as error:
        raise _http_error(error) from None
    return _response(view, response)


@router.put(
    "/items/{variant_id}",
    response_model=CartResponse,
    summary="Set the quantity of a variant in the cart",
)
async def set_cart_item_quantity(
    variant_id: VariantId,
    body: CartQuantityBody,
    response: Response,
    service: CartService,
    token: CartToken = None,
) -> CartResponse:
    try:
        view = await service.set_quantity(token, variant_id, body.quantity)
    except CartError as error:
        raise _http_error(error) from None
    return _response(view, response)


@router.delete(
    "/items/{variant_id}",
    response_model=CartResponse,
    summary="Remove a variant from the cart",
)
async def remove_cart_item(
    variant_id: VariantId,
    response: Response,
    service: CartService,
    token: CartToken = None,
) -> CartResponse:
    return _response(await service.remove_item(token, variant_id), response)
