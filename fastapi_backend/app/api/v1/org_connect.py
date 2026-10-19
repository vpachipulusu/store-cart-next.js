"""Stripe Connect onboarding API (KAN-67).

Same access rules as organisation billing: internal service key, verified session and an
OWNER or ADMIN membership of the organisation in the path. Errors are generic: no Stripe
text, ids or account data reach a response or a log.
"""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import require_internal_key
from app.api.deps import SessionDep
from app.api.me import CurrentUserIdDep
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.v1.auth import current_subject
from app.core.config import settings
from app.core.errors import ErrorResponse
from app.core.rate_limit import API_POLICY
from app.core.stripe_billing import StripeNotConfigured
from app.core.stripe_connect import StripeConnect, get_stripe_connect
from app.repositories.org_billing import OrgBillingRepository
from app.repositories.org_connect import OrgConnectRepository
from app.services.org_billing import (
    BillingForbidden,
    BillingUnavailable,
    InvalidReturnUrl,
    OrganizationNotFound,
    allowed_origins,
)
from app.services.stripe_connect import ConnectService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/organizations/{organization_id}/connect",
    tags=["organization-connect"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_subject(API_POLICY, current_subject)),
    ],
    responses={
        **RATE_LIMIT_FAIL_CLOSED_RESPONSES,
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
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


class ConnectStatusData(BaseModel):
    has_account: bool
    charges_enabled: bool
    payouts_enabled: bool
    details_submitted: bool


class ConnectStatusResponse(BaseModel):
    success: Literal[True] = True
    data: ConnectStatusData


class OnboardingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_url: str = Field(min_length=1, max_length=2048)
    refresh_url: str = Field(min_length=1, max_length=2048)


class OnboardingUrlData(BaseModel):
    url: str


class OnboardingUrlResponse(BaseModel):
    success: Literal[True] = True
    data: OnboardingUrlData


def stripe_connect() -> StripeConnect:
    try:
        return get_stripe_connect()
    except StripeNotConfigured:
        raise HTTPException(503, "Service temporarily unavailable") from None


def get_connect_service(
    session: SessionDep,
    stripe: Annotated[StripeConnect, Depends(stripe_connect)],
) -> ConnectService:
    return ConnectService(
        OrgBillingRepository(session),
        OrgConnectRepository(session),
        session,
        stripe,
        allowed_origins(settings.BILLING_RETURN_URL_ORIGINS),
    )


ServiceDep = Annotated[ConnectService, Depends(get_connect_service)]

HANDLED = (OrganizationNotFound, BillingForbidden, InvalidReturnUrl, BillingUnavailable)


def _mapped_error(exc: Exception) -> HTTPException:
    if isinstance(exc, OrganizationNotFound):
        return HTTPException(404, "Organization not found")
    if isinstance(exc, BillingForbidden):
        return HTTPException(403, "Forbidden")
    if isinstance(exc, InvalidReturnUrl):
        return HTTPException(422, "Invalid return URL")
    return HTTPException(502, "Payment provider unavailable")


def _http_error(exc: Exception) -> HTTPException:
    error = _mapped_error(exc)
    # Class and status only: the message and ids never reach the log.
    logger.log(
        logging.WARNING if error.status_code >= 500 else logging.INFO,
        "org connect request failed: cause=%s status=%s",
        type(exc).__name__,
        error.status_code,
    )
    return error


@router.get("", response_model=ConnectStatusResponse)
async def read_connect_status(
    organization_id: OrganizationId,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
) -> ConnectStatusResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        status = await service.status(organization_id, user_id)
    except HANDLED as exc:
        raise _http_error(exc) from None
    return ConnectStatusResponse(data=ConnectStatusData(**vars(status)))


@router.post("/onboarding-link", response_model=OnboardingUrlResponse)
async def create_onboarding_link(
    organization_id: OrganizationId,
    body: OnboardingRequest,
    response: Response,
    user_id: CurrentUserIdDep,
    service: ServiceDep,
    request_key: RequestKey = None,
) -> OnboardingUrlResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        url = await service.start_onboarding(
            organization_id,
            user_id,
            return_url=body.return_url,
            refresh_url=body.refresh_url,
            request_key=request_key,
        )
    except HANDLED as exc:
        raise _http_error(exc) from None
    return OnboardingUrlResponse(data=OnboardingUrlData(url=url))
