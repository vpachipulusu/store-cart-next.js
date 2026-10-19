"""Catalogue queries on one store database (KAN-245). No business rules.

Every function takes the ``AsyncSession`` of one store (opened by the store session
factory, the only door to a store database). There is no ORM model for store tables: the
SQL is explicit and every value is a bound parameter. Nothing here commits.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

from app.repositories.base import BaseRepository


@dataclass(frozen=True)
class ProductRow:
    id: str
    title: str
    slug: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class OptionValueRow:
    id: str
    option_id: str
    value: str
    position: int


@dataclass(frozen=True)
class OptionRow:
    id: str
    name: str
    position: int


@dataclass(frozen=True)
class VariantRow:
    id: str
    sku: str
    price_minor: int
    compare_at_price_minor: int | None
    weight_grams: int | None
    stock: int
    position: int


@dataclass(frozen=True)
class VariantChoice:
    variant_id: str
    option_id: str
    option_value_id: str


@dataclass(frozen=True)
class ImageRow:
    id: str
    storage_key: str
    alt_text: str | None
    position: int


@dataclass(frozen=True)
class ProductSummaryRow:
    id: str
    title: str
    slug: str
    status: str
    created_at: datetime
    updated_at: datetime
    variant_count: int
    min_price_minor: int | None
    max_price_minor: int | None


@dataclass(frozen=True)
class CategoryRow:
    id: str
    name: str
    slug: str
    parent_id: str | None
    position: int


# Advisory lock key serialising product creates; unique to this use within a store database.
PRODUCT_CREATE_LOCK_KEY = 0x5C0A0001

_LIST_FILTER = (
    "(CAST(:status AS varchar) IS NULL OR p.status = CAST(:status AS varchar)) "
    "AND (CAST(:category_id AS varchar) IS NULL OR EXISTS ("
    "SELECT 1 FROM product_categories pc "
    "WHERE pc.product_id = p.id AND pc.category_id = CAST(:category_id AS varchar))) "
    "AND (CAST(:pattern AS varchar) IS NULL "
    "OR p.title ILIKE CAST(:pattern AS varchar) ESCAPE '\\' "
    "OR EXISTS (SELECT 1 FROM variants sv WHERE sv.product_id = p.id "
    "AND sv.sku ILIKE CAST(:pattern AS varchar) ESCAPE '\\'))"
)


def search_pattern(query: str | None) -> str | None:
    """A contains-pattern for ILIKE with ``%``, ``_`` and the escape character neutralised."""
    if query is None:
        return None
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


_PRODUCT_UPDATABLE = frozenset({"title", "slug", "description", "status"})
_VARIANT_UPDATABLE = frozenset(
    {"sku", "price_minor", "compare_at_price_minor", "weight_grams", "stock"}
)
_VARIANT_COLUMNS = (
    "id, sku, price_minor, compare_at_price_minor, weight_grams, stock, position"
)


class StoreCatalogueRepository(BaseRepository):
    # --- products -----------------------------------------------------------------

    async def lock_product(self, product_id: str) -> bool:
        """Row-lock the product for the transaction; false when it does not exist."""
        row = (
            await self._session.execute(
                text("SELECT id FROM products WHERE id = :id FOR NO KEY UPDATE"),
                {"id": product_id},
            )
        ).first()
        return row is not None

    async def lock_catalogue(self) -> None:
        """Serialise product creates in this store until the transaction ends.

        A new product has no row to lock yet, so concurrent creates would each count the
        same total. The advisory lock is per database, and every store has its own.
        """
        # A stuck holder must not queue creates forever: 55P03 becomes "store is busy, retry".
        # SET LOCAL lasts until the transaction ends, so the timeout also covers the later
        # insert and commit; a timeout there surfaces as the 409 "The store is busy, retry".
        await self._session.execute(text("SET LOCAL lock_timeout = '5s'"))
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": PRODUCT_CREATE_LOCK_KEY}
        )

    async def set_transaction_timeouts(
        self, *, statement_ms: int, lock_ms: int
    ) -> None:
        """Bound each statement and each lock wait until the transaction ends (KAN-74).

        ``SET`` takes no bind parameters, so the values are checked as plain integers.
        """
        for name, value in (
            ("statement_timeout", statement_ms),
            ("lock_timeout", lock_ms),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive whole number of ms")
            await self._session.execute(text(f"SET LOCAL {name} = {value}"))

    async def count_all_products(self) -> int:
        """Every product, drafts included: the number the plan limit applies to."""
        return int(
            (
                await self._session.execute(text("SELECT count(*) FROM products"))
            ).scalar_one()
        )

    async def insert_product(
        self,
        *,
        product_id: str,
        title: str,
        slug: str,
        description: str | None,
        status: str,
    ) -> None:
        await self._session.execute(
            text(
                "INSERT INTO products (id, title, slug, description, status) "
                "VALUES (:id, :title, :slug, :description, :status)"
            ),
            {
                "id": product_id,
                "title": title,
                "slug": slug,
                "description": description,
                "status": status,
            },
        )

    async def update_product(self, product_id: str, changes: dict[str, object]) -> None:
        """Update the given columns (names come from the service, never the client)."""
        if not set(changes) <= _PRODUCT_UPDATABLE:
            raise ValueError("unexpected product column")
        assignments = ", ".join(
            [*(f"{column} = :{column}" for column in changes), "updated_at = now()"]
        )
        await self._session.execute(
            text(f"UPDATE products SET {assignments} WHERE id = :product_id"),
            {**changes, "product_id": product_id},
        )

    async def delete_product(self, product_id: str) -> bool:
        deleted = (
            await self._session.execute(
                text("DELETE FROM products WHERE id = :id RETURNING id"),
                {"id": product_id},
            )
        ).first()
        return deleted is not None

    async def get_product(self, product_id: str) -> ProductRow | None:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT id, title, slug, description, status, created_at, "
                        "updated_at FROM products WHERE id = :id"
                    ),
                    {"id": product_id},
                )
            )
            .mappings()
            .first()
        )
        return ProductRow(**row) if row is not None else None

    async def count_products(
        self, *, status: str | None, category_id: str | None, query: str | None = None
    ) -> int:
        return int(
            (
                await self._session.execute(
                    text("SELECT count(*) FROM products p WHERE " + _LIST_FILTER),
                    {
                        "status": status,
                        "category_id": category_id,
                        "pattern": search_pattern(query),
                    },
                )
            ).scalar_one()
        )

    async def list_products(
        self,
        *,
        status: str | None,
        category_id: str | None,
        limit: int,
        offset: int,
        query: str | None = None,
    ) -> list[ProductSummaryRow]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT p.id, p.title, p.slug, p.status, p.created_at, "
                        "p.updated_at, "
                        "(SELECT count(*) FROM variants v WHERE v.product_id = p.id) "
                        "AS variant_count, "
                        "(SELECT min(v.price_minor) FROM variants v "
                        "WHERE v.product_id = p.id) AS min_price_minor, "
                        "(SELECT max(v.price_minor) FROM variants v "
                        "WHERE v.product_id = p.id) AS max_price_minor "
                        "FROM products p WHERE "
                        + _LIST_FILTER
                        + " ORDER BY p.created_at DESC, p.id DESC "
                        "LIMIT :limit OFFSET :offset"
                    ),
                    {
                        "status": status,
                        "category_id": category_id,
                        "pattern": search_pattern(query),
                        "limit": limit,
                        "offset": offset,
                    },
                )
            )
            .mappings()
            .all()
        )
        return [ProductSummaryRow(**row) for row in rows]

    # --- options and variants -----------------------------------------------------

    async def insert_option(
        self, *, option_id: str, product_id: str, name: str, position: int
    ) -> None:
        await self._session.execute(
            text(
                "INSERT INTO product_options (id, product_id, name, position) "
                "VALUES (:id, :product_id, :name, :position)"
            ),
            {
                "id": option_id,
                "product_id": product_id,
                "name": name,
                "position": position,
            },
        )

    async def insert_option_value(
        self, *, value_id: str, option_id: str, value: str, position: int
    ) -> None:
        await self._session.execute(
            text(
                "INSERT INTO product_option_values (id, option_id, value, position) "
                "VALUES (:id, :option_id, :value, :position)"
            ),
            {
                "id": value_id,
                "option_id": option_id,
                "value": value,
                "position": position,
            },
        )

    async def insert_variant(
        self,
        *,
        variant_id: str,
        product_id: str,
        sku: str,
        price_minor: int,
        compare_at_price_minor: int | None,
        weight_grams: int | None,
        stock: int,
        position: int,
    ) -> None:
        await self._session.execute(
            text(
                "INSERT INTO variants (id, product_id, sku, price_minor, "
                "compare_at_price_minor, weight_grams, stock, position) "
                "VALUES (:id, :product_id, :sku, :price, :compare_at, :weight, "
                ":stock, :position)"
            ),
            {
                "id": variant_id,
                "product_id": product_id,
                "sku": sku,
                "price": price_minor,
                "compare_at": compare_at_price_minor,
                "weight": weight_grams,
                "stock": stock,
                "position": position,
            },
        )

    async def insert_variant_choice(
        self,
        *,
        variant_id: str,
        option_id: str,
        option_value_id: str,
        product_id: str,
    ) -> None:
        await self._session.execute(
            text(
                "INSERT INTO variant_option_values "
                "(variant_id, option_id, option_value_id, product_id) "
                "VALUES (:variant_id, :option_id, :option_value_id, :product_id)"
            ),
            {
                "variant_id": variant_id,
                "option_id": option_id,
                "option_value_id": option_value_id,
                "product_id": product_id,
            },
        )

    async def update_variant(
        self, variant_id: str, product_id: str, changes: dict[str, object]
    ) -> None:
        if not set(changes) <= _VARIANT_UPDATABLE:
            raise ValueError("unexpected variant column")
        assignments = ", ".join(
            [*(f"{column} = :{column}" for column in changes), "updated_at = now()"]
        )
        await self._session.execute(
            text(
                f"UPDATE variants SET {assignments} "
                "WHERE id = :variant_id AND product_id = :product_id"
            ),
            {**changes, "variant_id": variant_id, "product_id": product_id},
        )

    async def delete_variant(self, variant_id: str, product_id: str) -> bool:
        deleted = (
            await self._session.execute(
                text(
                    "DELETE FROM variants WHERE id = :variant_id "
                    "AND product_id = :product_id RETURNING id"
                ),
                {"variant_id": variant_id, "product_id": product_id},
            )
        ).first()
        return deleted is not None

    async def count_variants(self, product_id: str) -> int:
        return int(
            (
                await self._session.execute(
                    text("SELECT count(*) FROM variants WHERE product_id = :id"),
                    {"id": product_id},
                )
            ).scalar_one()
        )

    async def next_variant_position(self, product_id: str) -> int:
        return int(
            (
                await self._session.execute(
                    text(
                        "SELECT COALESCE(max(position), -1) + 1 FROM variants "
                        "WHERE product_id = :id"
                    ),
                    {"id": product_id},
                )
            ).scalar_one()
        )

    async def get_variant(self, variant_id: str, product_id: str) -> VariantRow | None:
        row = (
            (
                await self._session.execute(
                    text(
                        f"SELECT {_VARIANT_COLUMNS} FROM variants "
                        "WHERE id = :variant_id AND product_id = :product_id"
                    ),
                    {"variant_id": variant_id, "product_id": product_id},
                )
            )
            .mappings()
            .first()
        )
        return VariantRow(**row) if row is not None else None

    async def list_options(self, product_id: str) -> list[OptionRow]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT id, name, position FROM product_options "
                        "WHERE product_id = :id ORDER BY position, id"
                    ),
                    {"id": product_id},
                )
            )
            .mappings()
            .all()
        )
        return [OptionRow(**row) for row in rows]

    async def list_option_values(self, product_id: str) -> list[OptionValueRow]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT pov.id, pov.option_id, pov.value, pov.position "
                        "FROM product_option_values pov "
                        "JOIN product_options po ON po.id = pov.option_id "
                        "WHERE po.product_id = :id ORDER BY pov.position, pov.id"
                    ),
                    {"id": product_id},
                )
            )
            .mappings()
            .all()
        )
        return [OptionValueRow(**row) for row in rows]

    async def list_variants(self, product_id: str) -> list[VariantRow]:
        rows = (
            (
                await self._session.execute(
                    text(
                        f"SELECT {_VARIANT_COLUMNS} FROM variants "
                        "WHERE product_id = :id ORDER BY position, id"
                    ),
                    {"id": product_id},
                )
            )
            .mappings()
            .all()
        )
        return [VariantRow(**row) for row in rows]

    async def list_variant_choices(self, product_id: str) -> list[VariantChoice]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT variant_id, option_id, option_value_id "
                        "FROM variant_option_values WHERE product_id = :id"
                    ),
                    {"id": product_id},
                )
            )
            .mappings()
            .all()
        )
        return [VariantChoice(**row) for row in rows]

    async def existing_slugs(self, slugs: Sequence[str]) -> set[str]:
        """The given slugs that a product already uses (KAN-74)."""
        rows = await self._session.execute(
            text("SELECT slug FROM products WHERE slug = ANY(CAST(:s AS varchar[]))"),
            {"s": list(slugs)},
        )
        return {row[0] for row in rows}

    async def existing_skus(self, skus: Sequence[str]) -> set[str]:
        """The given SKUs, lower-cased, that a variant already uses (KAN-74).

        Matches ``uq_variants_sku_lower``, so the lookup uses that index.
        """
        rows = await self._session.execute(
            text(
                "SELECT lower(sku) FROM variants "
                "WHERE lower(sku) = ANY(CAST(:s AS varchar[]))"
            ),
            {"s": [sku.lower() for sku in skus]},
        )
        return {row[0] for row in rows}

    # --- categories ---------------------------------------------------------------

    async def existing_category_ids(self, category_ids: Sequence[str]) -> set[str]:
        rows = await self._session.execute(
            text("SELECT id FROM categories WHERE id = ANY(CAST(:ids AS varchar[]))"),
            {"ids": list(category_ids)},
        )
        return {row[0] for row in rows}

    async def list_categories(self, limit: int) -> list[CategoryRow]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT id, name, slug, parent_id, position FROM categories "
                        "ORDER BY parent_id NULLS FIRST, position, id LIMIT :limit"
                    ),
                    {"limit": limit},
                )
            )
            .mappings()
            .all()
        )
        return [CategoryRow(**row) for row in rows]

    async def replace_categories(
        self, product_id: str, category_ids: Sequence[str]
    ) -> None:
        await self._session.execute(
            text("DELETE FROM product_categories WHERE product_id = :id"),
            {"id": product_id},
        )
        if category_ids:
            await self._session.execute(
                text(
                    "INSERT INTO product_categories (product_id, category_id) "
                    "VALUES (:product_id, :category_id)"
                ),
                [
                    {"product_id": product_id, "category_id": category_id}
                    for category_id in category_ids
                ],
            )

    async def list_category_ids(self, product_id: str) -> list[str]:
        rows = await self._session.execute(
            text(
                "SELECT category_id FROM product_categories "
                "WHERE product_id = :id ORDER BY category_id"
            ),
            {"id": product_id},
        )
        return [row[0] for row in rows]

    # --- images -------------------------------------------------------------------

    async def insert_image(
        self,
        *,
        image_id: str,
        product_id: str,
        storage_key: str,
        alt_text: str | None,
        position: int,
    ) -> None:
        await self._session.execute(
            text(
                "INSERT INTO product_images "
                "(id, product_id, storage_key, alt_text, position) "
                "VALUES (:id, :product_id, :storage_key, :alt_text, :position)"
            ),
            {
                "id": image_id,
                "product_id": product_id,
                "storage_key": storage_key,
                "alt_text": alt_text,
                "position": position,
            },
        )

    async def delete_image(self, image_id: str, product_id: str) -> bool:
        deleted = (
            await self._session.execute(
                text(
                    "DELETE FROM product_images WHERE id = :image_id "
                    "AND product_id = :product_id RETURNING id"
                ),
                {"image_id": image_id, "product_id": product_id},
            )
        ).first()
        return deleted is not None

    async def count_images(self, product_id: str) -> int:
        return int(
            (
                await self._session.execute(
                    text("SELECT count(*) FROM product_images WHERE product_id = :id"),
                    {"id": product_id},
                )
            ).scalar_one()
        )

    async def next_image_position(self, product_id: str) -> int:
        return int(
            (
                await self._session.execute(
                    text(
                        "SELECT COALESCE(max(position), -1) + 1 FROM product_images "
                        "WHERE product_id = :id"
                    ),
                    {"id": product_id},
                )
            ).scalar_one()
        )

    async def list_images(self, product_id: str) -> list[ImageRow]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT id, storage_key, alt_text, position FROM product_images "
                        "WHERE product_id = :id ORDER BY position, id"
                    ),
                    {"id": product_id},
                )
            )
            .mappings()
            .all()
        )
        return [ImageRow(**row) for row in rows]
