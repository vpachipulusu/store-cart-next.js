"""Server-side shopper cart (KAN-76). No FastAPI imports.

The cart is keyed by an opaque token that the shopper's store-scoped cookie carries. Only its
SHA-256 is stored. The cart holds variant ids and quantities and nothing else: every call
re-reads name, price and stock from the catalogue and recomputes the totals with
``compute_totals``, so a price or stock change shows up on the next request and a client
can never name a price.

* A line is ``ok`` only when its product is active and the stock covers the quantity.
  Other lines are listed with the reason (``unavailable``, ``out_of_stock``, ``limited``)
  and left out of the totals; ``can_checkout`` is true only when every line is ``ok``.
* Writes check stock (and that the variant is sellable) before they change the cart, and
  take a row lock on the cart so two requests on one cart serialise. Stock is not reserved.
* An unknown, malformed or expired token reads as an empty cart; a write with one starts
  a new cart and returns its token once, in ``CartView.new_token``.
* Starting a cart is the only abusable write (it needs no account and the row lives 30 days), so it
  asks the ``CartCreationGuard`` (per-store hourly cap, KAN-252) after the request has been
  validated and before anything is inserted. A refused request creates nothing.
"""

import hashlib
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.repositories.store_cart import CartLineRow, StoreCartRepository, VariantRow
from app.services.store_cart_limits import CartCreationGuard
from app.services.store_orders import SELLABLE_PRODUCT_STATUS
from app.services.store_totals import LineAmount, Totals, TotalsSettings, compute_totals

CART_TTL_DAYS = 30
MAX_LINES = 50
MAX_QUANTITY = 99
EXPIRED_PURGE_LIMIT = 20
FOREIGN_KEY_VIOLATION = "23503"
VARIANT_FOREIGN_KEY = "fk_cart_items_variant"
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


class CartError(Exception):
    """A cart request that cannot be done. The message is safe to show the shopper."""


class ItemUnavailable(CartError):
    def __init__(self) -> None:
        super().__init__("That item is not available")


class CartConflict(CartError):
    """The request is valid but the cart or stock does not allow it (HTTP 409)."""


class LineStatus(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"
    OUT_OF_STOCK = "out_of_stock"
    LIMITED = "limited"


@dataclass(frozen=True)
class CartLine:
    variant_id: str
    product_id: str
    product_name: str
    product_slug: str
    sku: str
    variant_label: str | None
    unit_price_minor: int
    quantity: int
    line_total_minor: int
    available_stock: int
    status: LineStatus


@dataclass(frozen=True)
class CartView:
    lines: tuple[CartLine, ...]
    totals: Totals
    can_checkout: bool
    new_token: str | None = None


class CartSettings(Protocol):
    async def totals_settings(self) -> TotalsSettings: ...


def valid_token(token: str | None) -> bool:
    return token is not None and _TOKEN_PATTERN.fullmatch(token) is not None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def line_status(row: CartLineRow) -> LineStatus:
    if row.product_status != SELLABLE_PRODUCT_STATUS:
        return LineStatus.UNAVAILABLE
    if row.stock <= 0:
        return LineStatus.OUT_OF_STOCK
    if row.quantity > row.stock:
        return LineStatus.LIMITED
    return LineStatus.OK


def _to_line(row: CartLineRow) -> CartLine:
    return CartLine(
        variant_id=row.variant_id,
        product_id=row.product_id,
        product_name=row.product_name,
        product_slug=row.product_slug,
        sku=row.sku,
        variant_label=row.variant_label,
        unit_price_minor=row.price_minor,
        quantity=row.quantity,
        line_total_minor=row.price_minor * row.quantity,
        available_stock=row.stock,
        status=line_status(row),
    )


def build_view(
    rows: list[CartLineRow], settings: TotalsSettings, *, new_token: str | None = None
) -> CartView:
    lines = tuple(_to_line(row) for row in rows)
    priced = [
        LineAmount(unit_price_minor=line.unit_price_minor, quantity=line.quantity)
        for line in lines
        if line.status is LineStatus.OK
    ]
    return CartView(
        lines=lines,
        totals=compute_totals(priced, settings),
        can_checkout=bool(lines) and len(priced) == len(lines),
        new_token=new_token,
    )


def _check_sellable(variant: VariantRow | None, quantity: int) -> None:
    if variant is None or variant.product_status != SELLABLE_PRODUCT_STATUS:
        raise ItemUnavailable
    if variant.stock <= 0:
        raise CartConflict("That item is out of stock")
    if quantity > variant.stock:
        raise CartConflict(f"Only {variant.stock} in stock")


def _is_variant_gone(error: IntegrityError) -> bool:
    """True only for the cart_items -> variants foreign key violation."""
    original = error.orig
    for candidate in (original, getattr(original, "__cause__", None)):
        if (
            getattr(candidate, "sqlstate", None) == FOREIGN_KEY_VIOLATION
            and getattr(candidate, "constraint_name", None) == VARIANT_FOREIGN_KEY
        ):
            return True
    return False


class StoreCartService:
    def __init__(
        self,
        repository: StoreCartRepository,
        settings: CartSettings,
        session: AsyncSession,
        creation_guard: CartCreationGuard,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._session = session
        self._creation_guard = creation_guard

    async def view(self, token: str | None) -> CartView:
        """The priced cart; empty when the token is missing, unknown or expired."""
        settings = await self._settings.totals_settings()
        cart_id = await self._find(token)
        rows = await self._repository.list_lines(cart_id) if cart_id else []
        return build_view(rows, settings)

    async def add_item(
        self, token: str | None, variant_id: str, quantity: int
    ) -> CartView:
        """Add ``quantity`` of a variant (starting a cart when the token has none)."""
        return await self._write(token, variant_id, lambda current: current + quantity)

    async def set_quantity(
        self, token: str | None, variant_id: str, quantity: int
    ) -> CartView:
        """Set the quantity of a variant (adding the line when it is not there yet)."""
        return await self._write(token, variant_id, lambda _current: quantity)

    async def remove_item(self, token: str | None, variant_id: str) -> CartView:
        """Remove a line. A cart that does not exist stays absent (nothing is created)."""
        cart_id = await self._find(token)
        if cart_id is None:
            return await self.view(None)
        if not await self._repository.lock_cart(cart_id):
            return await self.view(None)
        await self._repository.delete_item(cart_id, variant_id)
        await self._repository.touch_cart(cart_id, ttl_days=CART_TTL_DAYS)
        await self._session.commit()
        return await self.view(token)

    async def _find(self, token: str | None) -> str | None:
        if token is None or not valid_token(token):
            return None
        return await self._repository.find_live_cart(hash_token(token))

    async def _write(
        self, token: str | None, variant_id: str, new_quantity: Callable[[int], int]
    ) -> CartView:
        cart_id = await self._find(token)
        if cart_id is not None and not await self._repository.lock_cart(cart_id):
            cart_id = None  # expired or purged between the lookup and the lock
        current = (
            await self._repository.get_quantity(cart_id, variant_id) if cart_id else 0
        )
        quantity = new_quantity(current)
        if not 1 <= quantity <= MAX_QUANTITY:
            raise CartConflict(f"Quantity must be 1 to {MAX_QUANTITY}")
        _check_sellable(await self._repository.get_variant(variant_id), quantity)
        if (
            cart_id is not None
            and current == 0
            and await self._repository.count_items(cart_id) >= MAX_LINES
        ):
            raise CartConflict(f"A cart holds at most {MAX_LINES} different items")
        issued: str | None = None
        if cart_id is None:
            await self._creation_guard.admit()
            await self._repository.delete_expired_carts(limit=EXPIRED_PURGE_LIMIT)
            issued = secrets.token_urlsafe(32)
            cart_id = new_id()
            await self._repository.insert_cart(
                cart_id=cart_id, token_hash=hash_token(issued), ttl_days=CART_TTL_DAYS
            )
        try:
            await self._repository.set_item(cart_id, variant_id, quantity)
            await self._repository.touch_cart(cart_id, ttl_days=CART_TTL_DAYS)
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            if _is_variant_gone(error):  # deleted after the check
                raise ItemUnavailable from None
            raise
        settings = await self._settings.totals_settings()
        rows = await self._repository.list_lines(cart_id)
        return build_view(rows, settings, new_token=issued)
