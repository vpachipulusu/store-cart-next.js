"""Cart queries on one store database (KAN-76). No business rules.

Takes the ``AsyncSession`` of one store (from the store session factory, the only door to a
store database) and never commits: the service owns the transaction. There is no ORM model
for store tables: explicit SQL, every value a bound parameter.

The cart stores only variant ids and quantities. ``list_lines`` joins the catalogue, so
names, prices and stock are always the current ones.
"""

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, text

from app.repositories.base import BaseRepository

MAX_LABEL_LENGTH = 255

_LINE_COLUMNS = """
    v.id AS variant_id, v.sku, v.price_minor, v.stock,
    p.id AS product_id, p.title AS product_name, p.slug AS product_slug,
    p.status AS product_status,
    (SELECT left(string_agg(pov.value, ' / ' ORDER BY po.position, po.id), :max_label)
       FROM variant_option_values vov
       JOIN product_options po ON po.id = vov.option_id
       JOIN product_option_values pov ON pov.id = vov.option_value_id
      WHERE vov.variant_id = v.id) AS variant_label
"""


@dataclass(frozen=True)
class CartLineRow:
    variant_id: str
    sku: str
    price_minor: int
    stock: int
    product_id: str
    product_name: str
    product_slug: str
    product_status: str
    variant_label: str | None
    quantity: int


@dataclass(frozen=True)
class VariantRow:
    variant_id: str
    stock: int
    product_status: str


class StoreCartRepository(BaseRepository):
    async def find_live_cart(self, token_hash: str) -> str | None:
        """The id of the unexpired cart with this token hash."""
        row = (
            await self._session.execute(
                text(
                    "SELECT id FROM carts "
                    "WHERE token_hash = :token_hash AND expires_at > now()"
                ),
                {"token_hash": token_hash},
            )
        ).first()
        return str(row[0]) if row is not None else None

    async def lock_cart(self, cart_id: str) -> bool:
        """Serialise writes to one cart until the transaction ends; false when it is gone.

        A cart can expire or be purged between the lookup and the lock, so the caller must
        check. An expired cart is never locked, so a write cannot revive it.
        """
        row = (
            await self._session.execute(
                text(
                    "SELECT id FROM carts "
                    "WHERE id = :id AND expires_at > now() FOR UPDATE"
                ),
                {"id": cart_id},
            )
        ).first()
        return row is not None

    async def insert_cart(
        self, *, cart_id: str, token_hash: str, ttl_days: int
    ) -> None:
        await self._session.execute(
            text(
                "INSERT INTO carts (id, token_hash, expires_at) "
                "VALUES (:id, :token_hash, now() + make_interval(days => :ttl_days))"
            ),
            {"id": cart_id, "token_hash": token_hash, "ttl_days": ttl_days},
        )

    async def touch_cart(self, cart_id: str, *, ttl_days: int) -> None:
        await self._session.execute(
            text(
                "UPDATE carts SET updated_at = now(), "
                "expires_at = now() + make_interval(days => :ttl_days) WHERE id = :id"
            ),
            {"id": cart_id, "ttl_days": ttl_days},
        )

    async def delete_expired_carts(self, *, limit: int) -> int:
        """Remove up to ``limit`` expired carts (their items cascade); returns how many."""
        result = await self._session.execute(
            text(
                "DELETE FROM carts WHERE id IN ("
                "SELECT id FROM carts WHERE expires_at <= now() "
                "ORDER BY expires_at LIMIT :limit FOR UPDATE SKIP LOCKED)"
            ),
            {"limit": limit},
        )
        return cast("CursorResult[Any]", result).rowcount

    async def get_variant(self, variant_id: str) -> VariantRow | None:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT v.id AS variant_id, v.stock, "
                        "p.status AS product_status "
                        "FROM variants v JOIN products p ON p.id = v.product_id "
                        "WHERE v.id = :id"
                    ),
                    {"id": variant_id},
                )
            )
            .mappings()
            .first()
        )
        return VariantRow(**row) if row is not None else None

    async def get_quantity(self, cart_id: str, variant_id: str) -> int:
        row = (
            await self._session.execute(
                text(
                    "SELECT quantity FROM cart_items "
                    "WHERE cart_id = :cart_id AND variant_id = :variant_id"
                ),
                {"cart_id": cart_id, "variant_id": variant_id},
            )
        ).first()
        return int(row[0]) if row is not None else 0

    async def count_items(self, cart_id: str) -> int:
        return int(
            (
                await self._session.execute(
                    text("SELECT count(*) FROM cart_items WHERE cart_id = :cart_id"),
                    {"cart_id": cart_id},
                )
            ).scalar_one()
        )

    async def set_item(self, cart_id: str, variant_id: str, quantity: int) -> None:
        await self._session.execute(
            text(
                "INSERT INTO cart_items (cart_id, variant_id, quantity) "
                "VALUES (:cart_id, :variant_id, :quantity) "
                "ON CONFLICT (cart_id, variant_id) "
                "DO UPDATE SET quantity = EXCLUDED.quantity"
            ),
            {"cart_id": cart_id, "variant_id": variant_id, "quantity": quantity},
        )

    async def delete_item(self, cart_id: str, variant_id: str) -> None:
        await self._session.execute(
            text(
                "DELETE FROM cart_items "
                "WHERE cart_id = :cart_id AND variant_id = :variant_id"
            ),
            {"cart_id": cart_id, "variant_id": variant_id},
        )

    async def list_lines(self, cart_id: str) -> list[CartLineRow]:
        rows = (
            (
                await self._session.execute(
                    text(
                        f"SELECT {_LINE_COLUMNS}, ci.quantity "
                        "FROM cart_items ci "
                        "JOIN variants v ON v.id = ci.variant_id "
                        "JOIN products p ON p.id = v.product_id "
                        "WHERE ci.cart_id = :cart_id "
                        "ORDER BY ci.added_at, ci.variant_id"
                    ),
                    {"cart_id": cart_id, "max_label": MAX_LABEL_LENGTH},
                )
            )
            .mappings()
            .all()
        )
        return [CartLineRow(**row) for row in rows]
