"""Read-only sales aggregates over one store database (KAN-96).

Takes the ``AsyncSession`` of one store, like ``store_orders``: there is no ORM model for store
tables, so the SQL is explicit and every value is a bound parameter. Each metric is one
statement aggregated in Postgres. Both filter ``orders`` on ``status = ANY(...)`` and a
``created_at`` range, which the existing orders indexes serve (``ix_orders_status_created_at``
from store revision 0004, or ``ix_orders_created_at`` from 0005).
Which statuses count as a sale is the service's rule, passed in.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class BucketSalesRow:
    currency: str
    bucket_start: date
    orders: int
    gross_minor: int
    refunds_minor: int


@dataclass(frozen=True)
class ProductSalesRow:
    currency: str
    product_name: str
    units: int
    revenue_minor: int
    revenue_rank: int
    units_rank: int


# Buckets are UTC calendar days, ISO weeks (Monday) or months. Refunds are the succeeded rows
# of each order, so a pending or failed refund never lowers the figures.
SALES_BY_BUCKET_SQL = text(
    """
    SELECT o.currency,
           CAST(date_trunc(CAST(:bucket AS text), o.created_at AT TIME ZONE 'UTC')
                AS date) AS bucket_start,
           CAST(count(*) AS bigint) AS orders,
           CAST(sum(o.total_minor) AS bigint) AS gross_minor,
           CAST(COALESCE(sum(r.refunded_minor), 0) AS bigint) AS refunds_minor
      FROM orders o
      LEFT JOIN LATERAL (
            SELECT sum(f.amount_minor) AS refunded_minor
              FROM order_refunds f
             WHERE f.order_id = o.id AND f.status = 'succeeded'
           ) r ON true
     WHERE o.status = ANY(CAST(:statuses AS varchar[]))
       AND o.created_at >= :since AND o.created_at < :until
     GROUP BY 1, 2
     ORDER BY 1, 2
    """
)

# Products are grouped by the name saved on the order line, so a renamed or deleted product
# still shows; its variants are one product. Revenue is the line price times quantity.
TOP_PRODUCTS_SQL = text(
    """
    WITH lines AS (
        SELECT o.currency, i.product_name,
               CAST(sum(i.quantity) AS bigint) AS units,
               CAST(sum(i.unit_price_minor * i.quantity) AS bigint) AS revenue_minor
          FROM orders o
          JOIN order_items i ON i.order_id = o.id
         WHERE o.status = ANY(CAST(:statuses AS varchar[]))
           AND o.created_at >= :since AND o.created_at < :until
         GROUP BY o.currency, i.product_name
    ), ranked AS (
        SELECT lines.*,
               row_number() OVER (
                   PARTITION BY currency
                   ORDER BY revenue_minor DESC, units DESC, product_name
               ) AS revenue_rank,
               row_number() OVER (
                   PARTITION BY currency
                   ORDER BY units DESC, revenue_minor DESC, product_name
               ) AS units_rank
          FROM lines
    )
    SELECT currency, product_name, units, revenue_minor,
           CAST(revenue_rank AS integer) AS revenue_rank,
           CAST(units_rank AS integer) AS units_rank
      FROM ranked
     WHERE revenue_rank <= :limit OR units_rank <= :limit
     ORDER BY currency, revenue_rank
    """
)


class StoreAnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def sales_by_bucket(
        self,
        *,
        since: datetime,
        until: datetime,
        bucket: str,
        statuses: Sequence[str],
    ) -> list[BucketSalesRow]:
        result = await self._session.execute(
            SALES_BY_BUCKET_SQL,
            {
                "since": since,
                "until": until,
                "bucket": bucket,
                "statuses": list(statuses),
            },
        )
        return [BucketSalesRow(**row) for row in result.mappings().all()]

    async def top_products(
        self,
        *,
        since: datetime,
        until: datetime,
        statuses: Sequence[str],
        limit: int,
    ) -> list[ProductSalesRow]:
        result = await self._session.execute(
            TOP_PRODUCTS_SQL,
            {
                "since": since,
                "until": until,
                "statuses": list(statuses),
                "limit": limit,
            },
        )
        return [ProductSalesRow(**row) for row in result.mappings().all()]
