"""Merchant order management on one store database (KAN-79). No FastAPI imports.

Works on the ``AsyncSession`` of the caller's own store (opened by the store session
factory, the only door to a store database). Reads list and show orders; ``fulfil`` is the
one write: it moves a ``paid`` order to ``fulfilled`` with a tracking number and commits once
(or rolls back and raises). An unknown id and an id of another store are the same
``OrderNotFound`` because the session only sees this store's tables.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.store_orders import (
    OrderItemRow,
    OrderRow,
    OrderSummaryRow,
    StoreOrdersRepository,
)
from app.services.store_orders import OrderNotFound, OrderStatus, fulfil_order

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
MAX_OFFSET = 100_000


@dataclass(frozen=True)
class OrderPage:
    items: tuple[OrderSummaryRow, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class OrderDetail:
    order: OrderRow
    items: tuple[OrderItemRow, ...]


class StoreOrdersService:
    def __init__(
        self, repository: StoreOrdersRepository, session: AsyncSession
    ) -> None:
        self._repository = repository
        self._session = session

    async def list_orders(
        self,
        *,
        status: OrderStatus | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> OrderPage:
        # The router bounds these too; the service is a boundary of its own.
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        offset = max(0, min(offset, MAX_OFFSET))
        status_value = status.value if status is not None else None
        rows = await self._repository.list_orders(
            status=status_value, limit=limit, offset=offset
        )
        total = await self._repository.count_orders(status=status_value)
        return OrderPage(items=tuple(rows), total=total, limit=limit, offset=offset)

    async def get(self, order_id: str) -> OrderDetail:
        order = await self._repository.get_order(order_id)
        if order is None:
            raise OrderNotFound(order_id)
        items = await self._repository.list_items(order_id)
        return OrderDetail(order=order, items=tuple(items))

    async def fulfil(
        self, order_id: str, tracking_number: str, carrier: str | None
    ) -> OrderDetail:
        try:
            await fulfil_order(self._session, order_id, tracking_number, carrier)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return await self.get(order_id)
