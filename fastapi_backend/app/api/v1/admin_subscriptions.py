"""Admin subscriptions API (KAN-48): list, detail, cancel, refund a payment, grant a plan.

Every route is ``require_admin(<permission>)``: authentication first (401), then the
admin record and permission (403, one generic body). Cancel needs ``subscriptions.update``,
refund ``subscriptions.refund`` and grant ``subscriptions.grant``. Stripe webhooks stay
the only writer of subscription state; see ``AdminSubscriptionsService``. Money-moving
routes require an ``Idempotency-Key`` header and map every Stripe failure to a generic
message: no Stripe text, card data or secrets reach a response.
"""

from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt

from app.api.admin import AuditorDep, require_admin
from app.api.auth import require_internal_key
from app.api.deps import SessionDep
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.v1.auth import current_subject
from app.core.errors import ErrorResponse
from app.core.permissions import AdminContext
from app.core.plans import PlanKey
from app.core.rate_limit import API_POLICY
from app.core.stripe_admin import (
    StripeAdminBilling,
    StripeCharge,
    get_stripe_admin,
)
from app.core.stripe_billing import StripeNotConfigured
from app.repositories.admin_subscriptions import (
    AdminSubscriptionsRepository,
    SubscriptionFilters,
    SubscriptionRecord,
)
from app.services.admin_subscriptions import (
    MAX_PAGE_SIZE,
    AdminSubscriptionsService,
    BillingNotConfigured,
    BillingUnavailable,
    CommitFailed,
    IdempotencyMismatch,
    InvalidGrant,
    PaymentNotFound,
    RefundExceedsBalance,
    StripeRefused,
    SubscriptionConflict,
    SubscriptionNotFound,
)

router = APIRouter(
    prefix="/v1/admin/subscriptions",
    tags=["admin-subscriptions"],
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
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]
SubscriptionStatus = Literal[
    "inactive",
    "active",
    "trialing",
    "past_due",
    "canceled",
    "unpaid",
    "incomplete",
    "incomplete_expired",
    "paused",
]
GrantablePlan = Literal["pro", "enterprise"]
# Stripe's largest amount: eight digits in the currency's minor unit.
MAX_REFUND_MINOR_UNITS = 99_999_999

ReadAdmin = Annotated[AdminContext, Depends(require_admin("subscriptions.read"))]
UpdateAdmin = Annotated[AdminContext, Depends(require_admin("subscriptions.update"))]
RefundAdmin = Annotated[AdminContext, Depends(require_admin("subscriptions.refund"))]
GrantAdmin = Annotated[AdminContext, Depends(require_admin("subscriptions.grant"))]


class SubscriptionSummary(BaseModel):
    organization_id: str
    name: str
    slug: str
    plan: PlanKey
    status: str
    current_period_end: datetime | None
    cancel_at_period_end: bool
    has_stripe_subscription: bool
    granted_plan: GrantablePlan | None
    granted_until: datetime | None
    created_at: datetime


class PaymentData(BaseModel):
    charge_id: str
    amount: int
    amount_refunded: int
    refundable: int
    currency: str
    status: str | None
    created: int
    invoice_id: str | None


class SubscriptionDetailData(SubscriptionSummary):
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    updated_at: datetime
    # null: Stripe is not configured or did not answer. Money fields only, no card data.
    payments: list[PaymentData] | None


class SubscriptionsPage(BaseModel):
    subscriptions: list[SubscriptionSummary]
    total_count: int
    limit: int
    offset: int


class SubscriptionsPageResponse(BaseModel):
    success: Literal[True] = True
    data: SubscriptionsPage


class SubscriptionDetailResponse(BaseModel):
    success: Literal[True] = True
    data: SubscriptionDetailData


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    immediately: bool = False


class CancelData(BaseModel):
    organization_id: str
    immediately: bool
    already_applied: bool


class CancelResponse(BaseModel):
    success: Literal[True] = True
    data: CancelData


class RefundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    charge_id: str = Field(pattern=r"^ch_[A-Za-z0-9]{1,128}$")
    # Minor units (pence, cents). Required, so a retry sends Stripe the same request.
    amount: StrictInt = Field(ge=1, le=MAX_REFUND_MINOR_UNITS)
    reason: Literal["duplicate", "fraudulent", "requested_by_customer"] | None = None


class RefundData(BaseModel):
    organization_id: str
    refund_id: str
    charge_id: str
    amount: int
    currency: str
    status: str | None
    already_applied: bool


class RefundResponse(BaseModel):
    success: Literal[True] = True
    data: RefundData


class GrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: GrantablePlan
    expires_at: AwareDatetime


class GrantData(BaseModel):
    organization_id: str
    granted_plan: GrantablePlan
    granted_until: datetime
    changed: bool


class GrantResponse(BaseModel):
    success: Literal[True] = True
    data: GrantData


def stripe_admin() -> StripeAdminBilling | None:
    """The Stripe admin client, or None when no secret key is set (reads still work)."""
    try:
        return get_stripe_admin()
    except StripeNotConfigured:
        return None


def get_admin_subscriptions_service(
    session: SessionDep,
    auditor: AuditorDep,
    stripe: Annotated[StripeAdminBilling | None, Depends(stripe_admin)],
) -> AdminSubscriptionsService:
    return AdminSubscriptionsService(
        AdminSubscriptionsRepository(session), session, stripe, auditor
    )


ServiceDep = Annotated[
    AdminSubscriptionsService, Depends(get_admin_subscriptions_service)
]

HANDLED = (
    SubscriptionNotFound,
    PaymentNotFound,
    SubscriptionConflict,
    RefundExceedsBalance,
    IdempotencyMismatch,
    StripeRefused,
    BillingUnavailable,
    BillingNotConfigured,
    CommitFailed,
    InvalidGrant,
)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SubscriptionNotFound):
        return HTTPException(404, "Organization not found")
    if isinstance(exc, PaymentNotFound):
        return HTTPException(404, "Payment not found")
    if isinstance(exc, SubscriptionConflict):
        return HTTPException(409, "Operation not allowed in the current state")
    if isinstance(exc, RefundExceedsBalance):
        return HTTPException(409, "Amount exceeds the refundable balance")
    if isinstance(exc, IdempotencyMismatch):
        return HTTPException(
            409, "Idempotency-Key was already used for another request"
        )
    if isinstance(exc, StripeRefused):
        return HTTPException(409, "The billing provider refused the request")
    if isinstance(exc, BillingUnavailable):
        return HTTPException(502, "Billing provider unavailable")
    if isinstance(exc, InvalidGrant):
        return HTTPException(422, "Invalid request")
    if isinstance(exc, CommitFailed):
        return HTTPException(
            503,
            "The result could not be recorded; retry with the same Idempotency-Key",
            {"Retry-After": "1"},
        )
    return HTTPException(503, "Billing is not configured")


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _grantable(plan: str | None) -> GrantablePlan | None:
    return cast(GrantablePlan, plan) if plan in ("pro", "enterprise") else None


def _summary(record: SubscriptionRecord, plan: PlanKey) -> SubscriptionSummary:
    return SubscriptionSummary(
        organization_id=record.id,
        name=record.name,
        slug=record.slug,
        plan=plan,
        status=record.subscription_status,
        current_period_end=record.stripe_current_period_end,
        cancel_at_period_end=record.stripe_cancel_at_period_end,
        has_stripe_subscription=record.stripe_subscription_id is not None,
        granted_plan=_grantable(record.granted_plan),
        granted_until=record.granted_until,
        created_at=record.created_at,
    )


def _payment(charge: StripeCharge) -> PaymentData:
    return PaymentData(
        charge_id=charge.id,
        amount=charge.amount,
        amount_refunded=charge.amount_refunded,
        refundable=charge.refundable,
        currency=charge.currency,
        status=charge.status,
        created=charge.created,
        invoice_id=charge.invoice_id,
    )


@router.get("", response_model=SubscriptionsPageResponse)
async def admin_list_subscriptions(
    response: Response,
    _admin: ReadAdmin,
    service: ServiceDep,
    status: SubscriptionStatus | None = None,
    plan: PlanKey | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> SubscriptionsPageResponse:
    _no_store(response)
    page = await service.list_subscriptions(
        SubscriptionFilters(status, plan), limit, offset
    )
    return SubscriptionsPageResponse(
        data=SubscriptionsPage(
            subscriptions=[
                _summary(item, service.plan_of(item)) for item in page.items
            ],
            total_count=page.total_count,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/{organization_id}", response_model=SubscriptionDetailResponse)
async def admin_read_subscription(
    organization_id: OrganizationId,
    response: Response,
    _admin: ReadAdmin,
    service: ServiceDep,
) -> SubscriptionDetailResponse:
    _no_store(response)
    try:
        detail = await service.get_detail(organization_id)
    except HANDLED as exc:
        raise _http_error(exc) from None
    record = detail.record
    payments = (
        None if detail.payments is None else [_payment(c) for c in detail.payments]
    )
    return SubscriptionDetailResponse(
        data=SubscriptionDetailData(
            **_summary(record, service.plan_of(record)).model_dump(),
            stripe_customer_id=record.stripe_customer_id,
            stripe_subscription_id=record.stripe_subscription_id,
            updated_at=record.updated_at,
            payments=payments,
        )
    )


@router.post("/{organization_id}/cancel", response_model=CancelResponse)
async def admin_cancel_subscription(
    organization_id: OrganizationId,
    response: Response,
    admin: UpdateAdmin,
    service: ServiceDep,
    request_key: RequestKey,
    body: CancelRequest | None = None,
) -> CancelResponse:
    _no_store(response)
    try:
        result = await service.cancel(
            admin,
            organization_id,
            immediately=body.immediately if body else False,
            request_key=request_key,
        )
    except HANDLED as exc:
        raise _http_error(exc) from None
    return CancelResponse(
        data=CancelData(
            organization_id=organization_id,
            immediately=result.immediately,
            already_applied=result.already_applied,
        )
    )


@router.post("/{organization_id}/refunds", response_model=RefundResponse)
async def admin_refund_payment(
    organization_id: OrganizationId,
    body: RefundRequest,
    response: Response,
    admin: RefundAdmin,
    service: ServiceDep,
    request_key: RequestKey,
) -> RefundResponse:
    _no_store(response)
    try:
        result = await service.refund(
            admin,
            organization_id,
            charge_id=body.charge_id,
            amount=body.amount,
            reason=body.reason,
            request_key=request_key,
        )
    except HANDLED as exc:
        raise _http_error(exc) from None
    return RefundResponse(
        data=RefundData(
            organization_id=organization_id,
            refund_id=result.refund_id,
            charge_id=result.charge_id,
            amount=result.amount,
            currency=result.currency,
            status=result.status,
            already_applied=result.already_applied,
        )
    )


@router.put("/{organization_id}/grant", response_model=GrantResponse)
async def admin_grant_subscription(
    organization_id: OrganizationId,
    body: GrantRequest,
    response: Response,
    admin: GrantAdmin,
    service: ServiceDep,
) -> GrantResponse:
    _no_store(response)
    try:
        result = await service.grant(
            admin, organization_id, plan=PlanKey(body.plan), until=body.expires_at
        )
    except HANDLED as exc:
        raise _http_error(exc) from None
    return GrantResponse(
        data=GrantData(
            organization_id=organization_id,
            granted_plan=cast(GrantablePlan, result.granted_plan),
            granted_until=result.granted_until,
            changed=result.changed,
        )
    )
