"""Merchant sales analytics API (KAN-96): sales, orders and top products over time.

Needs the internal service key, a verified session and an OWNER or ADMIN membership of the
organisation that owns ``{store_id}`` (``require_merchant``: unknown and foreign stores are the
same 404, STAFF get 403). The figures are read from that store's own database only. Read-only,
rate limited like the other merchant reads, and ``Cache-Control: no-store``. The definitions of
a sale, refunds, buckets and currencies are in ``app/services/store_analytics.py``.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.api.auth import require_internal_key
from app.api.merchant import OWNER_ADMIN
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.store_db import store_analytics_service
from app.api.v1.auth import current_subject
from app.api.v1.organizations import no_store
from app.core.errors import ErrorResponse
from app.core.rate_limit import API_POLICY
from app.services.store_analytics import (
    AnalyticsReport,
    Bucket,
    CurrencyAnalytics,
    InvalidAnalyticsRange,
    ProductSales,
    SalesPoint,
    StoreAnalyticsService,
)

router = APIRouter(
    prefix="/v1/stores/{store_id}/analytics",
    tags=["analytics"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_subject(API_POLICY, current_subject)),
    ],
    responses={
        **RATE_LIMIT_FAIL_CLOSED_RESPONSES,
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)

AnalyticsService = Annotated[
    StoreAnalyticsService, Depends(store_analytics_service(OWNER_ADMIN))
]


class SalesTotalsData(BaseModel):
    orders: int = Field(description="Orders counted as sales")
    gross_sales_minor: int = Field(
        description="Sum of order totals, in minor units of the currency"
    )
    refunds_minor: int = Field(
        description="Succeeded refunds of those orders, in minor units"
    )
    net_sales_minor: int = Field(description="Gross sales minus refunds")


class SalesPointData(SalesTotalsData):
    bucket_start: date = Field(
        description="First UTC day of the bucket (a Monday for weeks, the 1st for months)"
    )


class TopProductData(BaseModel):
    product_name: str = Field(description="The product name saved on the order lines")
    units: int
    revenue_minor: int = Field(description="Unit price times quantity, before refunds")


class CurrencyAnalyticsData(BaseModel):
    currency: str = Field(description="ISO 4217 code; amounts are never converted")
    totals: SalesTotalsData
    series: list[SalesPointData] = Field(
        description="One entry per bucket in the range, oldest first, zeros included"
    )
    top_products_by_revenue: list[TopProductData] = Field(max_length=10)
    top_products_by_units: list[TopProductData] = Field(max_length=10)


class StoreAnalyticsData(BaseModel):
    start_date: date = Field(description="First UTC day of the range")
    end_date: date = Field(description="Last UTC day of the range (inclusive)")
    bucket: Bucket
    currencies: list[CurrencyAnalyticsData] = Field(
        description="One entry per currency with sales in the range; empty without sales"
    )


class StoreAnalyticsResponse(BaseModel):
    data: StoreAnalyticsData


def _totals(point: SalesPoint) -> dict[str, int]:
    return {
        "orders": point.orders,
        "gross_sales_minor": point.gross_minor,
        "refunds_minor": point.refunds_minor,
        "net_sales_minor": point.net_minor,
    }


def _product(product: ProductSales) -> TopProductData:
    return TopProductData(
        product_name=product.product_name,
        units=product.units,
        revenue_minor=product.revenue_minor,
    )


def _currency(entry: CurrencyAnalytics) -> CurrencyAnalyticsData:
    return CurrencyAnalyticsData(
        currency=entry.currency,
        totals=SalesTotalsData(**_totals(entry.totals)),
        series=[
            SalesPointData(bucket_start=point.start, **_totals(point))
            for point in entry.series
        ],
        top_products_by_revenue=[_product(p) for p in entry.top_by_revenue],
        top_products_by_units=[_product(p) for p in entry.top_by_units],
    )


def analytics_response(report: AnalyticsReport) -> StoreAnalyticsResponse:
    return StoreAnalyticsResponse(
        data=StoreAnalyticsData(
            start_date=report.start,
            end_date=report.end,
            bucket=report.bucket,
            currencies=[_currency(entry) for entry in report.currencies],
        )
    )


@router.get(
    "",
    response_model=StoreAnalyticsResponse,
    summary="Sales, orders and top products over time",
)
async def read_store_analytics(
    response: Response,
    service: AnalyticsService,
    start: Annotated[
        date | None,
        Query(
            alias="from",
            description="First UTC day (YYYY-MM-DD); defaults to 29 days before `to`",
        ),
    ] = None,
    end: Annotated[
        date | None,
        Query(
            alias="to",
            description="Last UTC day, inclusive (YYYY-MM-DD); defaults to today",
        ),
    ] = None,
    bucket: Annotated[Bucket, Query(description="Series granularity")] = Bucket.DAY,
) -> StoreAnalyticsResponse:
    """Paid, fulfilled and refunded orders of the store, per currency, net of refunds.

    The range is at most 366 days and ``from`` must not be after ``to`` (422 otherwise).
    """
    no_store(response)
    try:
        report = await service.report(start=start, end=end, bucket=bucket)
    except InvalidAnalyticsRange as error:
        raise HTTPException(
            422, str(error), headers={"Cache-Control": "no-store"}
        ) from None
    return analytics_response(report)
