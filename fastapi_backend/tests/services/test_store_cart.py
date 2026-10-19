"""Cart pricing rules without a database (KAN-76): line status, totals and token format."""

import pytest

from app.repositories.store_cart import CartLineRow, VariantRow
from app.services.store_cart import (
    CartConflict,
    ItemUnavailable,
    LineStatus,
    _check_sellable,
    build_view,
    hash_token,
    line_status,
    valid_token,
)
from app.services.store_totals import TotalsSettings

NO_EXTRAS = TotalsSettings(
    shipping_flat_rate_minor=0,
    free_shipping_threshold_minor=None,
    tax_rate_bps=0,
    prices_include_tax=False,
)


def row(
    *, price: int = 1000, stock: int = 5, quantity: int = 1, status: str = "active"
) -> CartLineRow:
    return CartLineRow(
        variant_id="v1",
        sku="SKU-1",
        price_minor=price,
        stock=stock,
        product_id="p1",
        product_name="Mug",
        product_slug="mug",
        product_status=status,
        variant_label=None,
        quantity=quantity,
    )


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (row(stock=5, quantity=5), LineStatus.OK),
        (row(stock=4, quantity=5), LineStatus.LIMITED),
        (row(stock=0, quantity=1), LineStatus.OUT_OF_STOCK),
        (row(status="draft"), LineStatus.UNAVAILABLE),
        (row(status="draft", stock=0), LineStatus.UNAVAILABLE),
    ],
)
def test_line_status(line: CartLineRow, expected: LineStatus) -> None:
    assert line_status(line) is expected


def test_only_ok_lines_count_toward_the_totals() -> None:
    view = build_view(
        [row(price=1000, quantity=2), row(stock=0, price=9999)], NO_EXTRAS
    )

    assert view.totals.subtotal_minor == 2000
    assert view.can_checkout is False


def test_an_empty_cart_cannot_check_out() -> None:
    view = build_view([], NO_EXTRAS)

    assert view.lines == ()
    assert view.totals.total_minor == 0
    assert view.can_checkout is False


def test_the_line_total_is_price_times_quantity_even_when_not_ok() -> None:
    view = build_view([row(price=250, quantity=3, stock=1)], NO_EXTRAS)

    assert view.lines[0].line_total_minor == 750
    assert view.totals.subtotal_minor == 0


def test_shipping_and_tax_use_the_store_settings() -> None:
    settings = TotalsSettings(499, None, 2000, False)

    view = build_view([row(price=1000, quantity=2)], settings)

    assert (view.totals.shipping_minor, view.totals.tax_minor) == (499, 400)
    assert view.totals.total_minor == 2899


def test_a_fresh_token_is_accepted_and_junk_is_not() -> None:
    assert valid_token("A" * 43)
    assert not any(
        valid_token(value) for value in (None, "", "short", "A" * 44, "!" * 43)
    )


def test_the_stored_hash_is_not_the_token() -> None:
    token = "A" * 43

    assert hash_token(token) != token
    assert len(hash_token(token)) == 64


def test_a_draft_or_missing_variant_is_unavailable() -> None:
    with pytest.raises(ItemUnavailable):
        _check_sellable(None, 1)
    with pytest.raises(ItemUnavailable):
        _check_sellable(VariantRow("v1", 5, "draft"), 1)


def test_stock_limits_are_conflicts_with_a_plain_message() -> None:
    with pytest.raises(CartConflict, match="Only 2 in stock"):
        _check_sellable(VariantRow("v1", 2, "active"), 3)
    with pytest.raises(CartConflict, match="out of stock"):
        _check_sellable(VariantRow("v1", 0, "active"), 1)
