"""Public platform settings (KAN-205): ``GET /v1/settings/currency``.

Called only by the Next.js server (decision D14), so it needs the internal service key
but no user session. It exposes the currency code and nothing else from ``app_settings``;
add another route, with its own schema, to expose another setting.

The body is identical for every caller, so it is cacheable: ``Cache-Control: private`` plus a
content-hash ``ETag`` answered with 304 on ``If-None-Match`` (same scheme as the
storefront lookup).
"""

import hashlib
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel

from app.api.auth import require_internal_key
from app.api.deps import SessionDep
from app.api.rate_limit import RATE_LIMIT_RESPONSES, limit_by_client_ip
from app.core.config import settings
from app.core.errors import ErrorResponse
from app.core.rate_limit import PUBLIC_SETTINGS_POLICY
from app.core.stripe_prices import get_stripe_prices
from app.repositories.app_settings import AppSettingsRepository
from app.services.plan_prices import PlanPricesService
from app.services.public_settings import PublicSettingsService

SUCCESS_CACHE_CONTROL = "private, max-age=60, stale-while-revalidate=300"
# Stripe prices change rarely; the Next.js server caches them for an hour on top of this.
PLAN_PRICES_CACHE_CONTROL = "private, max-age=300"

router = APIRouter(
    prefix="/v1/settings",
    tags=["settings"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_client_ip(PUBLIC_SETTINGS_POLICY)),
    ],
    responses={**RATE_LIMIT_RESPONSES, 401: {"model": ErrorResponse}},
)


class CurrencyData(BaseModel):
    """The public fields. Add a field here only when it is safe for anyone to read."""

    currency: str


class CurrencyResponse(BaseModel):
    success: Literal[True] = True
    data: CurrencyData


def get_settings_service(session: SessionDep) -> PublicSettingsService:
    return PublicSettingsService(AppSettingsRepository(session))


ServiceDep = Annotated[PublicSettingsService, Depends(get_settings_service)]


def _etag_for(body: bytes) -> str:
    return f'"{hashlib.sha256(body).hexdigest()[:32]}"'


def _matches(if_none_match: str | None, etag: str) -> bool:
    """RFC 9110 weak comparison of an ``If-None-Match`` list against ``etag``."""
    if if_none_match is None:
        return False
    candidates = [part.strip() for part in if_none_match.split(",")]
    return "*" in candidates or any(c.removeprefix("W/") == etag for c in candidates)


@router.get(
    "/currency",
    response_model=CurrencyResponse,
    summary="Read the platform currency",
    responses={304: {"description": "Not modified (If-None-Match matched)"}},
)
async def read_currency(
    service: ServiceDep,
    if_none_match: Annotated[
        str | None, Header(description="ETag from an earlier response")
    ] = None,
) -> Response:
    """The platform currency code (upper case, e.g. ``USD``).

    Answers ``USD`` when the setting is missing or not a supported code. Sends
    ``Cache-Control: private, max-age=60`` and an ``ETag``.
    """
    currency = await service.currency()
    etag = _etag_for(currency.encode())
    headers = {"Cache-Control": SUCCESS_CACHE_CONTROL, "ETag": etag}
    if _matches(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    content = CurrencyResponse(data=CurrencyData(currency=currency)).model_dump_json()
    return Response(content, media_type="application/json", headers=headers)


class TierPricesData(BaseModel):
    """Minor units (cents) of the Stripe price; null when unconfigured or unreadable."""

    monthly: int | None
    yearly: int | None


class PlanPricesData(BaseModel):
    pro: TierPricesData
    enterprise: TierPricesData


class PlanPricesResponse(BaseModel):
    success: Literal[True] = True
    data: PlanPricesData


def get_plan_prices_service() -> PlanPricesService:
    return PlanPricesService(
        get_stripe_prices(),
        {
            ("pro", "monthly"): settings.STRIPE_PRICE_ID_PRO_MONTHLY or "",
            ("pro", "yearly"): settings.STRIPE_PRICE_ID_PRO_YEARLY or "",
            ("enterprise", "monthly"): settings.STRIPE_PRICE_ID_ENTERPRISE_MONTHLY
            or "",
            ("enterprise", "yearly"): settings.STRIPE_PRICE_ID_ENTERPRISE_YEARLY or "",
        },
    )


PlanPricesServiceDep = Annotated[PlanPricesService, Depends(get_plan_prices_service)]


@router.get(
    "/plan-prices",
    response_model=PlanPricesResponse,
    summary="Read the subscription plan prices",
)
async def read_plan_prices(service: PlanPricesServiceDep) -> Response:
    """Stripe unit amounts for the paid plans, in minor units.

    A price that is not configured or cannot be read is ``null``; the caller falls back
    to its default. Sends ``Cache-Control: private, max-age=300``.
    """
    prices = await service.prices()
    body = PlanPricesResponse(
        data=PlanPricesData(
            pro=TierPricesData(monthly=prices.pro.monthly, yearly=prices.pro.yearly),
            enterprise=TierPricesData(
                monthly=prices.enterprise.monthly, yearly=prices.enterprise.yearly
            ),
        )
    )
    return Response(
        body.model_dump_json(),
        media_type="application/json",
        headers={"Cache-Control": PLAN_PRICES_CACHE_CONTROL},
    )
