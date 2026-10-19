"""Seeds an ACTIVE store with a small catalogue for the local storefront theme e2e (KAN-75).

Reuses seed_cart.py to create and provision the store, then adds a category tree (Kitchen > Mugs), a published
mug with a Size option (S out of stock, M in stock) in Mugs, a published kettle with no category, and a draft
lamp. Prints one JSON line with the slugs. It is not part of the app.

Usage (from fastapi_backend/, with the same environment as uvicorn):
    PYTHONPATH=. uv run python <this file> <store-slug>
"""

import asyncio
import json
import sys

from seed_cart import create_store, provision
from sqlalchemy import text

from app.core.ids import new_id
from app.services.store_sessions import get_store_session


async def insert_product(
    session, *, title: str, slug: str, status: str, description: str | None = None
) -> str:  # type: ignore[no-untyped-def]
    product_id = new_id()
    await session.execute(
        text(
            "INSERT INTO products (id, title, slug, description, status) "
            "VALUES (:p, :t, :s, :d, :st)"
        ),
        {"p": product_id, "t": title, "s": slug, "d": description, "st": status},
    )
    return product_id


async def insert_variant(  # type: ignore[no-untyped-def]
    session, product_id: str, *, price: int, stock: int, position: int = 0
) -> str:
    variant_id = new_id()
    await session.execute(
        text(
            "INSERT INTO variants (id, product_id, sku, price_minor, stock, position) "
            "VALUES (:v, :p, :sku, :price, :stock, :pos)"
        ),
        {
            "v": variant_id,
            "p": product_id,
            "sku": f"E2E-THEME-{variant_id[:8]}",
            "price": price,
            "stock": stock,
            "pos": position,
        },
    )
    return variant_id


async def seed_catalogue(store_id: str) -> dict[str, str]:
    kitchen, mugs = new_id(), new_id()
    async with get_store_session(store_id) as session:
        await session.execute(
            text(
                "INSERT INTO categories (id, name, slug, parent_id, position) VALUES "
                "(:k, 'Kitchen', 'kitchen', NULL, 0), (:m, 'Mugs', 'mugs', :k, 0)"
            ),
            {"k": kitchen, "m": mugs},
        )

        mug = await insert_product(
            session,
            title="Blue Stoneware Mug",
            slug="blue-stoneware-mug",
            status="active",
            description="A heavy stoneware mug.\nDishwasher safe.",
        )
        option = new_id()
        small, medium = new_id(), new_id()
        await session.execute(
            text(
                "INSERT INTO product_options (id, product_id, name, position) "
                "VALUES (:o, :p, 'Size', 0)"
            ),
            {"o": option, "p": mug},
        )
        await session.execute(
            text(
                "INSERT INTO product_option_values (id, option_id, value, position) VALUES "
                "(:s, :o, 'Small', 0), (:m, :o, 'Medium', 1)"
            ),
            {"s": small, "m": medium, "o": option},
        )
        for value_id, price, stock, position in ((small, 1250, 0, 0), (medium, 1450, 4, 1)):
            variant = await insert_variant(
                session, mug, price=price, stock=stock, position=position
            )
            await session.execute(
                text(
                    "INSERT INTO variant_option_values "
                    "(variant_id, option_id, option_value_id, product_id) "
                    "VALUES (:v, :o, :val, :p)"
                ),
                {"v": variant, "o": option, "val": value_id, "p": mug},
            )
        await session.execute(
            text("INSERT INTO product_categories (product_id, category_id) VALUES (:p, :c)"),
            {"p": mug, "c": mugs},
        )

        kettle = await insert_product(
            session, title="Copper Kettle", slug="copper-kettle", status="active"
        )
        await insert_variant(session, kettle, price=3900, stock=2)

        lamp = await insert_product(
            session, title="Secret Desk Lamp", slug="secret-desk-lamp", status="draft"
        )
        await insert_variant(session, lamp, price=2500, stock=3)
        await session.commit()
    return {
        "mugSlug": "blue-stoneware-mug",
        "kettleSlug": "copper-kettle",
        "draftSlug": "secret-desk-lamp",
    }


async def main(slug: str) -> None:
    store_id = await create_store(slug)
    await provision(store_id)
    print(json.dumps({"storeId": store_id, **await seed_catalogue(store_id)}))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: seed_storefront.py <store-slug>")
    asyncio.run(main(sys.argv[1]))
