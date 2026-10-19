"""Seeds an ACTIVE store with a catalogue for the local cart e2e (KAN-76).

Creates an organisation and an ACTIVE store row directly in the platform database (no user, no login), runs
the real provisioning steps inline (as activate_store.py does), then inserts one active product (stock 5,
price 1250) and one draft product into the store database. Prints one JSON line with the variant ids.
It is not part of the app.

Usage (from fastapi_backend/, with the same environment as uvicorn):
    PYTHONPATH=. uv run python <this file> <store-slug>
"""

import asyncio
import json
import sys

from sqlalchemy import text

from app.core.config import settings
from app.core.database import DefaultSessionProvider, async_session_maker
from app.core.ids import new_id
from app.services.store_provisioning import get_database_provisioner
from app.services.store_provisioning_job import Step, StepRunner
from app.services.store_sessions import get_store_session


class InlineEnqueuer:
    """Collects the next step the runner asks for, so this script can run it itself."""

    def __init__(self) -> None:
        self.pending: list[Step] = []

    async def enqueue(self, store_id: str, step: Step, *, attempt: int) -> None:
        self.pending.append(step)


async def create_store(slug: str) -> str:
    org_id, store_id = new_id(), new_id()
    async with async_session_maker() as session:
        await session.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:i, :n, :s)"),
            {"i": org_id, "n": f"Cart e2e {slug}", "s": slug},
        )
        await session.execute(
            text(
                "INSERT INTO stores (id, organization_id, name, slug, status) "
                "VALUES (:i, :o, :n, :s, 'PROVISIONING')"
            ),
            {"i": store_id, "o": org_id, "n": f"Cart Shop {slug}", "s": slug},
        )
        await session.commit()
    return store_id


async def provision(store_id: str) -> None:
    enqueuer = InlineEnqueuer()
    runner = StepRunner(
        provider=DefaultSessionProvider(async_session_maker),
        provisioner=lambda: get_database_provisioner(settings),
        enqueuer=enqueuer,
    )
    await runner.run(Step.CREATE_DATABASE, store_id)
    while enqueuer.pending:
        await runner.run(enqueuer.pending.pop(0), store_id)


async def seed_catalogue(store_id: str) -> dict[str, str]:
    products = {"active": new_id(), "draft": new_id()}
    variants = {"active": new_id(), "draft": new_id()}
    async with get_store_session(store_id) as session:
        for kind, price in (("active", 1250), ("draft", 999)):
            await session.execute(
                text(
                    "INSERT INTO products (id, title, slug, status) "
                    "VALUES (:p, :t, :s, :st)"
                ),
                {
                    "p": products[kind],
                    "t": f"E2E {kind} mug",
                    "s": f"e2e-{kind}-mug",
                    "st": kind,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO variants (id, product_id, sku, price_minor, stock) "
                    "VALUES (:v, :p, :sku, :price, 5)"
                ),
                {
                    "v": variants[kind],
                    "p": products[kind],
                    "sku": f"E2E-CART-{kind}-{variants[kind][:6]}",
                    "price": price,
                },
            )
        await session.commit()
    return {"activeVariantId": variants["active"], "draftVariantId": variants["draft"]}


async def main(slug: str) -> None:
    store_id = await create_store(slug)
    await provision(store_id)
    print(json.dumps({"storeId": store_id, **await seed_catalogue(store_id)}))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: seed_cart.py <store-slug>")
    asyncio.run(main(sys.argv[1]))
