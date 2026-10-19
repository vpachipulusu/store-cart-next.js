"""Seeds orders into a store database for the local order-management e2e (KAN-79).

There is no checkout yet, so the only way to get an order into a store is the order service. This creates one
active product with one variant and then a PAID order and a PENDING order for it. It is not part of the app.

Usage (from fastapi_backend/, with the same environment as uvicorn):
    PYTHONPATH=. uv run python <this file> <store_id>
"""

import asyncio
import sys

from sqlalchemy import text

from app.core.ids import new_id
from app.services.store_orders import (
    OrderLineInput,
    OrderStatus,
    create_order,
    transition_order,
)
from app.services.store_sessions import get_store_session

SKU = "E2E-ORDER-1"
TITLE = "E2E Order Tee"


async def main(store_id: str) -> None:
    product_id, variant_id = new_id(), new_id()
    async with get_store_session(store_id) as session:
        await session.execute(
            text(
                "INSERT INTO products (id, title, slug, status) "
                "VALUES (:p, :t, 'e2e-order-tee', 'active')"
            ),
            {"p": product_id, "t": TITLE},
        )
        await session.execute(
            text(
                "INSERT INTO variants (id, product_id, sku, price_minor) "
                "VALUES (:v, :p, :s, 1999)"
            ),
            {"v": variant_id, "p": product_id, "s": SKU},
        )
        lines = [OrderLineInput(variant_id=variant_id, quantity=2)]
        paid = await create_order(
            session, currency="GBP", tax_rate_bps=2000, lines=lines
        )
        await transition_order(session, paid.id, OrderStatus.PAID)
        await create_order(session, currency="GBP", tax_rate_bps=2000, lines=lines)
        await session.commit()
        print(paid.id)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: seed_orders.py <store_id>")
    asyncio.run(main(sys.argv[1]))
