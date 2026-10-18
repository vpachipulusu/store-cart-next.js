"""Organisation billing API (KAN-43).

Every route needs the internal service key, a verified session and an OWNER or ADMIN
membership of the organisation in the path (``OrgBillingService.authorize``). Routes ask
Stripe to act and return; subscription state is written only by the Stripe webhook.
Errors are generic: no Stripe text, ids or customer data reach a response or a log.
"""

import logging
from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import require_internal_key
from app.api.deps import SessionDep
from app.api.me import CurrentUserIdDep
from app.api.rate_limit import (
    RATE_LIMIT_FAIL_CLOSED_RESPONSES,
    client_ip,
    limit_by_subject,
)
from app.api.v1.auth import current_subject
from app.core.config import settings
from app.core.errors import ErrorResponse
from app.core.plans import PlanKey
from app.core.rate_limit import API_POLICY
from app.core.stripe_billing import (
    StripeBilling,
    StripeNotConfigured,
    get_stripe_billing,
)
from app.repositories.org_billing import OrgBillingRepository
from app.services.org_billing import (
    BillingConflict,
    BillingForbidden,
    BillingNotConfigured,
    BillingUnavailable,
    InvalidReturnUrl,
    OrganizationNotFound,
    OrgBillingService,
    PaymentMethodNotFound,
    PriceCatalogue,
    RequestOrigin,
    allowed_origins,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/organizations/{organization_id}/billing",
    tags=["organization-billing"],
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
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)

OrganizationId = Annotated[
    str, Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]
RequestKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]
RequiredRequestKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]
PaymentMethodId = Annotated[
    str, Path(min_length=4, max_length=255, pattern=r"^pm_[A-Za-z0-9]+$")
]
PlanName = Literal["pro", "enterprise"]
Interval = Literal["monthly", "yearly"]


class PlanData(BaseModel):
    key: str
    name: str
    max_stores: int | None
    max_products: int | None
    max_staff: int | None


class BillingData(BaseModel):
    plan: PlanData
    subscription_status: str
    current_period_end: datetime | None
    has_billing_account: bool
    has_subscription: bool
    cancel_at_period_end: bool
    interval: Interval | None


class BillingResponse(BaseModel):
    success: Literal[True] = True
    data: BillingData


class UrlData(BaseModel):
    url: str


class UrlResponse(BaseModel):
    success: Literal[True] = True
    data: UrlData


class OkResponse(BaseModel):
    success: Literal[True] = True


class InvoiceData(BaseModel):
    id: str
    number: str | None
    status: str | None
    amount_due: int
    amount_paid: int
    currency: str
    created: int
    hosted_invoice_url: str | None
    invoice_pdf: str | None


class InvoicesResponse(BaseModel):
    success: Literal[True] = True
    data: list[InvoiceData]


class PaymentMethodData(BaseModel):
    id: str
    brand: str | None
    last4: str | None
    exp_month: int | None
    exp_year: int | None
    is_default: bool


class PaymentMethodsResponse(BaseModel):
    success: Literal[True] = True
    data: list[PaymentMethodData]


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: PlanName
    interval: Interval
    success_url: str = Field(min_length=1, max_length=2048)
    cancel_url: str = Field(min_length=1, max_length=2048)


class PortalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_url: str = Field(min_length=1, max_length=2048)


class ChangePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: PlanName
    interval: Interval


def price_catalogue() -> PriceCatalogue:
    """(plan, interval) to Stripe price id, from settings; unset prices are left out."""
    configured = {
        (PlanKey.PRO, "monthly"): settings.STRIPE_PRICE_ID_PRO_MONTHLY,
        (PlanKey.PRO, "yearly"): settings.STRIPE_PRICE_ID_PRO_YEARLY,
        (PlanKey.ENTERPRISE, "monthly"): settings.STRIPE_PRICE_ID_ENTERPRISE_MONTHLY,
        (PlanKey.ENTERPRISE, "yearly"): settings.STRIPE_PRICE_ID_ENTERPRISE_YEARLY,
    }
    return {key: price for key, price in configured.items() if price}


def stripe_billing() -> StripeBilling:
    try:
        return get_stripe_billing()
    except StripeNotConfigured:
        raise HTTPException(503, "Service temporarily unavailable") from None


def _audit_ip(request: Request) -> str | None:
    ip = client_ip(request)
    return None if ip == "unknown" else ip


def get_org_billing_service(
    request: Request,
    session: SessionDep,
    stripe: Annotated[StripeBilling, Depends(stripe_billing)],
) -> OrgBillingService:
    return OrgBillingService(
        OrgBillingRepository(session),
        session,
        stripe,
        price_catalogue(),
        allowed_origins(settings.BILLING_RETURN_URL_ORIGINS),
        RequestOrigin(
            ip_address=_audit_ip(request),
            user_agent=request.headers.get("user-agent"),
            request_id=getattr(request.state, "request_id", None),
        ),
    )


ServiceDep = Annotated[OrgBillingService, Depends(get_org_billing_service)]

HANDLED = (
    OrganizationNotFound,
    PaymentMethodNotFound,
    BillingForbidden,
    BillingConflict,
    InvalidReturnUrl,
    BillingNotConfigured,
    BillingUnavailable,
)


def _http_error(exc: Exception) -> HTTPException:
    error = _mapped_error(exc)
    # The class and status name the cause for operators; the message and ids never reach the log.
    logger.warning(
        "org billing request failed: cause=%s status=%s",
        type(exc).__name__,
        error.status_code,
    )
    return error


def _mapped_error(exc: Exception) -> HTTPException:
    if isinstance(exc, OrganizationNotFound):
        return HTTPException(404, "Organization not found")
    if isinstance(exc, PaymentMethodNotFound):
        return HTTPException(404, "Payment method not found")
    if isinstance(exc, BillingForbidden):
        return HTTPException(403, "Forbidden")
    if isinstance(exc, BillingConflict):
        return HTTPException(409, "Operation not allowed in the current state")
    if isinstance(exc, InvalidReturnUrl):
        return HTTPException(422, "Invalid return URL")
    if isinstance(exc, BillingNotConfigured):
        return HTTPException(503, "Service temporarily unavailable")
    return HTTPException(502, "Billing provider unavailable")


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("", response_model=BillingResponse)
async def read_billing(
    organization_id: OrganizationId,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
) -> BillingResponse:
    _no_store(response)
    try:
        summary = await service.summary(organization_id, user_id)
    except HANDLED as exc:
        raise _http_error(exc) from None
    plan = summary.plan
    return BillingResponse(
        data=BillingData(
            plan=PlanData(
                key=plan.key.value,
                name=plan.name,
                max_stores=plan.max_stores,
                max_products=plan.max_products,
                max_staff=plan.max_staff,
            ),
            subscription_status=summary.status,
            current_period_end=summary.current_period_end,
            has_billing_account=summary.has_billing_account,
            has_subscription=summary.has_subscription,
            cancel_at_period_end=summary.cancel_at_period_end,
            interval=cast(Interval | None, summary.interval),
        )
    )


@router.post("/checkout", response_model=UrlResponse)
async def create_checkout(
    organization_id: OrganizationId,
    body: CheckoutRequest,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
    request_key: RequestKey = None,
) -> UrlResponse:
    _no_store(response)
    try:
        url = await service.start_checkout(
            organization_id,
            user_id,
            plan=PlanKey(body.plan),
            interval=body.interval,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
            request_key=request_key,
        )
    except HANDLED as exc:
        raise _http_error(exc) from None
    return UrlResponse(data=UrlData(url=url))


@router.post("/portal", response_model=UrlResponse)
async def create_portal(
    organization_id: OrganizationId,
    body: PortalRequest,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
    request_key: RequestKey = None,
) -> UrlResponse:
    _no_store(response)
    try:
        url = await service.open_portal(
            organization_id,
            user_id,
            return_url=body.return_url,
            request_key=request_key,
        )
    except HANDLED as exc:
        raise _http_error(exc) from None
    return UrlResponse(data=UrlData(url=url))


@router.post("/plan", response_model=OkResponse)
async def change_plan(
    organization_id: OrganizationId,
    body: ChangePlanRequest,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
    request_key: RequestKey = None,
) -> OkResponse:
    _no_store(response)
    try:
        await service.change_plan(
            organization_id,
            user_id,
            plan=PlanKey(body.plan),
            interval=body.interval,
            request_key=request_key,
        )
    except HANDLED as exc:
        raise _http_error(exc) from None
    return OkResponse()


@router.post("/cancel", response_model=OkResponse)
async def cancel_subscription(
    organization_id: OrganizationId,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
    request_key: RequestKey = None,
) -> OkResponse:
    _no_store(response)
    try:
        await service.set_cancellation(
            organization_id, user_id, cancel=True, request_key=request_key
        )
    except HANDLED as exc:
        raise _http_error(exc) from None
    return OkResponse()


@router.post("/resume", response_model=OkResponse)
async def resume_subscription(
    organization_id: OrganizationId,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
    request_key: RequestKey = None,
) -> OkResponse:
    _no_store(response)
    try:
        await service.set_cancellation(
            organization_id, user_id, cancel=False, request_key=request_key
        )
    except HANDLED as exc:
        raise _http_error(exc) from None
    return OkResponse()


@router.get("/invoices", response_model=InvoicesResponse)
async def list_invoices(
    organization_id: OrganizationId,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
) -> InvoicesResponse:
    _no_store(response)
    try:
        invoices = await service.invoices(organization_id, user_id)
    except HANDLED as exc:
        raise _http_error(exc) from None
    return InvoicesResponse(data=[InvoiceData(**vars(item)) for item in invoices])


@router.get("/payment-methods", response_model=PaymentMethodsResponse)
async def list_payment_methods(
    organization_id: OrganizationId,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
) -> PaymentMethodsResponse:
    _no_store(response)
    try:
        methods = await service.payment_methods(organization_id, user_id)
    except HANDLED as exc:
        raise _http_error(exc) from None
    return PaymentMethodsResponse(data=[PaymentMethodData(**vars(m)) for m in methods])


@router.delete("/payment-methods/{payment_method_id}", response_model=OkResponse)
async def delete_payment_method(
    organization_id: OrganizationId,
    payment_method_id: PaymentMethodId,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
    request_key: RequiredRequestKey,
) -> OkResponse:
    _no_store(response)
    try:
        await service.delete_payment_method(
            organization_id, user_id, payment_method_id, request_key=request_key
        )
    except HANDLED as exc:
        raise _http_error(exc) from None
    return OkResponse()


@router.post("/payment-methods/{payment_method_id}/default", response_model=OkResponse)
async def set_default_payment_method(
    organization_id: OrganizationId,
    payment_method_id: PaymentMethodId,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
    request_key: RequiredRequestKey,
) -> OkResponse:
    _no_store(response)
    try:
        await service.set_default_payment_method(
            organization_id, user_id, payment_method_id, request_key=request_key
        )
    except HANDLED as exc:
        raise _http_error(exc) from None
    return OkResponse()
