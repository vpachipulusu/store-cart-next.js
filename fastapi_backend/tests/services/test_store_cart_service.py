"""Cart service writes with a fake repository (KAN-76): no database.

Covers the paths a real database makes hard to reach on purpose: a cart that disappears
between the lookup and the lock, a variant deleted between the check and the insert, and
the quantity and line limits.
"""

from typing import Any, cast

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.store_cart import CartLineRow, StoreCartRepository, VariantRow
from app.services import store_cart
from app.services.store_cart import (
    CartConflict,
    ItemUnavailable,
    StoreCartService,
    hash_token,
)
from app.services.store_totals import TotalsSettings

TOKEN = "A" * 43
SETTINGS = TotalsSettings(0, None, 0, False)


class FakeSettings:
    async def totals_settings(self) -> TotalsSettings:
        return SETTINGS


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class DriverError(Exception):
    def __init__(self, sqlstate: str, constraint_name: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate
        self.constraint_name = constraint_name


class FakeCartRepository:
    """Carts in memory. ``locked`` decides whether lock_cart finds the cart."""

    def __init__(self) -> None:
        self.carts: dict[str, str] = {}  # token hash -> cart id
        self.items: dict[str, dict[str, int]] = {}
        self.variants = {"v1": VariantRow("v1", 200, "active")}
        self.locked = True
        self.set_error: Exception | None = None

    async def find_live_cart(self, token_hash: str) -> str | None:
        return self.carts.get(token_hash)

    async def lock_cart(self, cart_id: str) -> bool:
        return self.locked and cart_id in self.items

    async def insert_cart(
        self, *, cart_id: str, token_hash: str, ttl_days: int
    ) -> None:
        self.carts[token_hash] = cart_id
        self.items[cart_id] = {}

    async def touch_cart(self, cart_id: str, *, ttl_days: int) -> None:
        return None

    async def delete_expired_carts(self, *, limit: int) -> None:
        return None

    async def get_variant(self, variant_id: str) -> VariantRow | None:
        return self.variants.get(variant_id)

    async def get_quantity(self, cart_id: str, variant_id: str) -> int:
        return self.items[cart_id].get(variant_id, 0)

    async def count_items(self, cart_id: str) -> int:
        return len(self.items[cart_id])

    async def set_item(self, cart_id: str, variant_id: str, quantity: int) -> None:
        if self.set_error is not None:
            raise self.set_error
        self.items[cart_id][variant_id] = quantity

    async def delete_item(self, cart_id: str, variant_id: str) -> None:
        self.items[cart_id].pop(variant_id, None)

    async def list_lines(self, cart_id: str) -> list[CartLineRow]:
        return [
            CartLineRow(
                variant_id=variant_id,
                sku=f"SKU-{variant_id}",
                price_minor=100,
                stock=self.variants[variant_id].stock,
                product_id="p1",
                product_name="Mug",
                product_slug="mug",
                product_status="active",
                variant_label=None,
                quantity=quantity,
            )
            for variant_id, quantity in self.items[cart_id].items()
        ]


def build(repo: FakeCartRepository) -> tuple[StoreCartService, FakeSession]:
    session = FakeSession()
    service = StoreCartService(
        cast(StoreCartRepository, repo), FakeSettings(), cast(AsyncSession, session)
    )
    return service, session


def with_cart(repo: FakeCartRepository, **items: int) -> None:
    repo.carts[hash_token(TOKEN)] = "cart-1"
    repo.items["cart-1"] = dict(items)


def integrity_error(sqlstate: str, constraint: str) -> IntegrityError:
    return IntegrityError("INSERT", {}, cast(Any, DriverError(sqlstate, constraint)))


async def test_a_cart_gone_before_the_lock_starts_a_new_one_with_a_new_token() -> None:
    repo = FakeCartRepository()
    with_cart(repo, v1=1)
    repo.locked = False
    service, _ = build(repo)

    view = await service.add_item(TOKEN, "v1", 2)

    assert view.new_token not in (None, TOKEN)
    assert [line.quantity for line in view.lines] == [2]


async def test_removing_from_a_cart_gone_before_the_lock_changes_nothing() -> None:
    repo = FakeCartRepository()
    with_cart(repo, v1=1)
    repo.locked = False
    service, session = build(repo)

    view = await service.remove_item(TOKEN, "v1")

    assert view.lines == ()
    assert repo.items["cart-1"] == {"v1": 1}
    assert session.commits == 0


async def test_a_variant_deleted_before_the_insert_is_unavailable() -> None:
    repo = FakeCartRepository()
    with_cart(repo)
    repo.set_error = integrity_error("23503", "fk_cart_items_variant")
    service, session = build(repo)

    with pytest.raises(ItemUnavailable):
        await service.add_item(TOKEN, "v1", 1)

    assert session.rollbacks == 1


async def test_any_other_integrity_error_is_not_hidden() -> None:
    repo = FakeCartRepository()
    with_cart(repo)
    repo.set_error = integrity_error("23503", "fk_cart_items_cart")
    service, session = build(repo)

    with pytest.raises(IntegrityError):
        await service.add_item(TOKEN, "v1", 1)

    assert session.rollbacks == 1


async def test_adding_past_the_quantity_limit_is_refused() -> None:
    repo = FakeCartRepository()
    with_cart(repo)
    service, _ = build(repo)
    await service.add_item(TOKEN, "v1", 60)

    with pytest.raises(CartConflict, match="Quantity must be 1 to 99"):
        await service.add_item(TOKEN, "v1", 50)

    assert repo.items["cart-1"] == {"v1": 60}


async def test_a_full_cart_refuses_a_new_variant_but_accepts_an_existing_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store_cart, "MAX_LINES", 1)
    repo = FakeCartRepository()
    repo.variants["v2"] = VariantRow("v2", 50, "active")
    with_cart(repo, v1=1)
    service, _ = build(repo)

    with pytest.raises(CartConflict, match="at most 1 different items"):
        await service.add_item(TOKEN, "v2", 1)
    view = await service.add_item(TOKEN, "v1", 1)

    assert [line.quantity for line in view.lines] == [2]


async def test_a_write_without_a_token_issues_one_and_a_write_with_one_does_not() -> (
    None
):
    repo = FakeCartRepository()
    service, _ = build(repo)

    first = await service.add_item(None, "v1", 1)
    assert first.new_token is not None
    second = await service.add_item(first.new_token, "v1", 1)

    assert second.new_token is None
    assert [line.quantity for line in second.lines] == [2]
