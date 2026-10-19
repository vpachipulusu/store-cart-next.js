"""Read access to the orders of one store database (KAN-79).

Takes the ``AsyncSession`` of one store (from the store session factory); there is no ORM model
for store tables, so the SQL is explicit and every value is a bound parameter. Reads only:
order writes live in ``app/services/store_orders.py``.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class OrderSummaryRow:
    id: str
    status: str
    currency: str
    total_minor: int
    tracking_number: str | None
    carrier: str | None
    fulfilled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    item_count: int


@dataclass(frozen=True)
class OrderRow:
    id: str
    status: str
    currency: str
    subtotal_minor: int
    tax_minor: int
    total_minor: int
    tracking_number: str | None
    carrier: str | None
    fulfilled_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class OrderItemRow:
    id: str
    product_name: str
    sku: str
    variant_label: str | None
    unit_price_minor: int
    quantity: int
    tax_rate_bps: int
    tax_minor: int


_LIST_SQL = text(
    """
    SELECT o.id, o.status, o.currency, o.total_minor, o.tracking_number, o.carrier,
           o.fulfilled_at, o.created_at, o.updated_at,
           CAST((SELECT COALESCE(sum(i.quantity), 0) FROM order_items i
                  WHERE i.order_id = o.id) AS bigint) AS item_count
      FROM orders o
     WHERE (CAST(:status AS varchar) IS NULL OR o.status = CAST(:status AS varchar))
     ORDER BY o.created_at DESC, o.id DESC
     LIMIT :limit OFFSET :offset
    """
)
_COUNT_SQL = text(
    "SELECT count(*) FROM orders "
    "WHERE (CAST(:status AS varchar) IS NULL OR status = CAST(:status AS varchar))"
)
_ORDER_SQL = text(
    "SELECT id, status, currency, subtotal_minor, tax_minor, total_minor,"
    " tracking_number, carrier, fulfilled_at, created_at, updated_at "
    "FROM orders WHERE id = :id"
)
_ITEMS_SQL = text(
    "SELECT id, product_name, sku, variant_label, unit_price_minor, quantity,"
    " tax_rate_bps, tax_minor FROM order_items "
    "WHERE order_id = :id ORDER BY created_at, id"
)


class StoreOrdersRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_orders(
        self, *, status: str | None, limit: int, offset: int
    ) -> list[OrderSummaryRow]:
        rows = (
            (
                await self._session.execute(
                    _LIST_SQL, {"status": status, "limit": limit, "offset": offset}
                )
            )
            .mappings()
            .all()
        )
        return [OrderSummaryRow(**row) for row in rows]

    async def count_orders(self, *, status: str | None) -> int:
        return int(
            (await self._session.execute(_COUNT_SQL, {"status": status})).scalar_one()
        )

    async def get_order(self, order_id: str) -> OrderRow | None:
        row = (
            (await self._session.execute(_ORDER_SQL, {"id": order_id}))
            .mappings()
            .first()
        )
        return OrderRow(**row) if row is not None else None

    async def list_items(self, order_id: str) -> list[OrderItemRow]:
        rows = (
            (await self._session.execute(_ITEMS_SQL, {"id": order_id})).mappings().all()
        )
        return [OrderItemRow(**row) for row in rows]
