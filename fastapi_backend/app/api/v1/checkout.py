"""Public storefront checkout (KAN-68): ``POST /v1/storefront/{slug}/checkout``.

Called only by the Next.js server (decision D14), so it needs the internal service key but no
user session. The shopper's cart travels in ``X-Cart-Token`` like the cart routes. The body
names only the return URLs (the store's own host ``{slug}.<PLATFORM_ROOT_DOMAIN>``, or an
app origin on ``BILLING_RETURN_URL_ORIGINS``); every amount is computed on the server from the catalogue and
the store settings, and anything else in the body is a 422.

The answer is the Stripe-hosted ``checkout_url`` (a direct charge on the store organisation's
connected account) and the ``pending`` order id. The order becomes ``paid`` only when the
Connect webhook confirms the session. Responses are ``no-store``.
"""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import require_internal_key
from app.api.deps import get_session_provider
from app.api.rate_limit import (
    RATE_LIMIT_FAIL_CLOSED_RESPONSES,
    limit_by_client_ip,
)
from app.api.store_db import (
    NO_STORE_HEADERS,
    STORE_UNAVAILABLE,
    storefront_checkout_service,
)
from app.core.config import settings
from app.core.database import SessionProvider
from app.core.errors import ErrorResponse
from app.core.rate_limit import CHECKOUT_POLICY
from app.core.stripe_billing import StripeNotConfigured
from app.core.stripe_checkout import StripeCheckout, get_stripe_checkout
from app.services.org_billing import MAX_URL_LENGTH, allowed_origins
from app.services.store_checkout import (
    CartNotReady,
    CheckoutError,
    CheckoutStoreNotFound,
    CheckoutUnavailable,
    InvalidCheckoutUrl,
    PaymentInProgress,
    PaymentsNotEnabled,
    StoreCheckoutService,
)
from app.services.store_sessions import StoreSessionError

logger = logging.getLogger(__name__)

NOT_CONFIGURED = "Payments are not available right now"

router = APIRouter(
    prefix="/v1/storefront/{slug}/checkout",
    tags=["checkout"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_client_ip(CHECKOUT_POLICY)),
    ],
    responses={
        **RATE_LIMIT_FAIL_CLOSED_RESPONSES,
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {
            "model": ErrorResponse,
            "description": (
                "Rate limiter, Stripe configuration or store database unavailable"
            ),
        },
    },
)


def get_stripe_checkout_client() -> StripeCheckout:
    try:
        return get_stripe_checkout()
    except StripeNotConfigured:
        raise HTTPException(503, NOT_CONFIGURED, headers=NO_STORE_HEADERS) from None


def get_checkout_service(
    provider: Annotated[SessionProvider, Depends(get_session_provider)],
    stripe: Annotated[StripeCheckout, Depends(get_stripe_checkout_client)],
) -> StoreCheckoutService:
    return storefront_checkout_service(
        provider,
        stripe,
        allowed_origins(settings.BILLING_RETURN_URL_ORIGINS),
        settings.PLATFORM_ROOT_DOMAIN,
    )


CartToken = Annotated[
    str | None,
    Header(
        alias="X-Cart-Token",
        max_length=128,
        description="The shopper's cart token. Missing, unknown or expired is an empty cart (409).",
    ),
]


class CheckoutBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success_url: str = Field(min_length=1, max_length=MAX_URL_LENGTH)
    cancel_url: str = Field(min_length=1, max_length=MAX_URL_LENGTH)


class CheckoutData(BaseModel):
    order_id: str
    checkout_url: str = Field(description="Stripe-hosted payment page. Redirect to it.")


class CheckoutResponse(BaseModel):
    success: Literal[True] = True
    data: CheckoutData


def _status_for(error: CheckoutError) -> int:
    if isinstance(error, CheckoutStoreNotFound):
        return 404
    if isinstance(error, PaymentsNotEnabled | CartNotReady | PaymentInProgress):
        return 409
    if isinstance(error, InvalidCheckoutUrl):
        return 422
    if isinstance(error, CheckoutUnavailable):
        return 502
    return 500  # every CheckoutError is mapped above


@router.post(
    "",
    response_model=CheckoutResponse,
    summary="Start a checkout for the cart",
    description=(
        "Creates a pending order priced on the server and a Stripe Checkout Session on the "
        "store's connected account, or returns the open one when the cart is unchanged since "
        "the last start. 409 when payments are not enabled, the cart is empty or has changed, "
        "or its earlier checkout is already being paid; 422 when a return URL is not the store's subdomain or an allowed "
        "app origin; 502 when Stripe fails."
    ),
)
async def start_checkout(
    slug: str,
    body: CheckoutBody,
    response: Response,
    service: Annotated[StoreCheckoutService, Depends(get_checkout_service)],
    token: CartToken = None,
) -> CheckoutResponse:
    try:
        started = await service.start(slug, token, body.success_url, body.cancel_url)
    except CheckoutError as error:
        raise HTTPException(
            _status_for(error), str(error), headers=NO_STORE_HEADERS
        ) from None
    except StoreSessionError as error:
        reason = type(error).__name__
        logger.error(
            "store database unavailable: %s",
            reason,
            extra={"store_id": error.store_id, "reason": reason},
        )
        raise HTTPException(503, STORE_UNAVAILABLE, headers=NO_STORE_HEADERS) from None
    response.headers["Cache-Control"] = NO_STORE_HEADERS["Cache-Control"]
    return CheckoutResponse(
        data=CheckoutData(order_id=started.order_id, checkout_url=started.checkout_url)
    )
