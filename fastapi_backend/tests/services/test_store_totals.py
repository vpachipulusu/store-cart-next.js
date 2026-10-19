"""Server-side order totals with shipping and tax (KAN-82, KAN-83). Pure, no database."""

import pytest

from app.services.store_totals import (
    LineAmount,
    TotalsSettings,
    compute_totals,
    shipping_minor,
)


def settings(
    *,
    flat: int = 0,
    threshold: int | None = None,
    tax_bps: int = 0,
    included: bool = False,
) -> TotalsSettings:
    return TotalsSettings(
        shipping_flat_rate_minor=flat,
        free_shipping_threshold_minor=threshold,
        tax_rate_bps=tax_bps,
        prices_include_tax=included,
    )


def test_charges_the_flat_rate_when_there_is_no_threshold() -> None:
    assert shipping_minor(5_000, settings(flat=499)) == 499


def test_shipping_is_free_at_the_threshold() -> None:
    assert shipping_minor(5_000, settings(flat=499, threshold=5_000)) == 0


def test_charges_shipping_just_below_the_threshold() -> None:
    assert shipping_minor(4_999, settings(flat=499, threshold=5_000)) == 499


def test_no_shipping_for_an_empty_basket() -> None:
    assert shipping_minor(0, settings(flat=499)) == 0


def test_adds_shipping_to_the_total() -> None:
    totals = compute_totals([LineAmount(1_000, 2)], settings(flat=499))

    assert (totals.subtotal_minor, totals.shipping_minor, totals.tax_minor) == (
        2_000,
        499,
        0,
    )
    assert totals.total_minor == 2_499


def test_free_shipping_applies_to_the_item_subtotal_before_tax() -> None:
    totals = compute_totals(
        [LineAmount(4_500, 1)],
        settings(flat=499, threshold=5_000, tax_bps=2_000),
    )

    assert totals.shipping_minor == 499  # 4500 < 5000, tax does not count


def test_adds_tax_on_top_when_prices_exclude_tax() -> None:
    totals = compute_totals([LineAmount(1_000, 3)], settings(tax_bps=2_000))

    assert totals.tax_minor == 600
    assert totals.total_minor == 3_600
    assert totals.prices_include_tax is False


def test_rounds_tax_half_up_per_line() -> None:
    totals = compute_totals(
        [LineAmount(105, 1), LineAmount(105, 1)], settings(tax_bps=1_000)
    )

    assert totals.tax_minor == 22  # 10.5 -> 11 per line


def test_extracts_tax_when_prices_include_it() -> None:
    totals = compute_totals(
        [LineAmount(1_200, 1)], settings(flat=300, tax_bps=2_000, included=True)
    )

    assert totals.subtotal_minor == 1_200
    assert totals.tax_minor == 200  # 1200 - 1200/1.2
    assert totals.total_minor == 1_500  # tax is already inside the prices
    assert totals.prices_include_tax is True


def test_zero_rate_means_no_tax_either_way() -> None:
    for included in (False, True):
        totals = compute_totals([LineAmount(999, 1)], settings(included=included))
        assert totals.tax_minor == 0 and totals.total_minor == 999


def test_empty_basket_totals_zero() -> None:
    totals = compute_totals([], settings(flat=499, tax_bps=2_000))

    assert totals.total_minor == 0 and totals.shipping_minor == 0


@pytest.mark.parametrize("price,quantity", [(-1, 1), (1, 0), (1, -2)])
def test_rejects_negative_amounts_and_empty_quantities(
    price: int, quantity: int
) -> None:
    with pytest.raises(ValueError):
        compute_totals([LineAmount(price, quantity)], settings())


def test_tax_inclusive_rounding_gives_net_half_up_and_tax_the_rest() -> None:
    totals = compute_totals(
        [LineAmount(105, 1)], settings(tax_bps=1_000, included=True)
    )

    assert totals.tax_minor == 10  # net 95.45 -> 95, tax 105 - 95
    assert totals.total_minor == 105


def test_tax_inclusive_tax_can_round_down_to_zero() -> None:
    totals = compute_totals([LineAmount(1, 1)], settings(tax_bps=2_000, included=True))

    assert totals.tax_minor == 0


def test_tax_inclusive_at_one_hundred_percent_is_half_the_gross() -> None:
    totals = compute_totals(
        [LineAmount(200, 1)], settings(tax_bps=10_000, included=True)
    )

    assert totals.tax_minor == 100


def test_tax_inclusive_tax_is_rounded_per_line() -> None:
    totals = compute_totals(
        [LineAmount(105, 1), LineAmount(105, 1)], settings(tax_bps=1_000, included=True)
    )

    assert totals.tax_minor == 20  # 10 + 10, not 19 from rounding the 210 once


def test_free_shipping_threshold_compares_the_gross_subtotal_when_prices_include_tax() -> (
    None
):
    totals = compute_totals(
        [LineAmount(5_000, 1)],
        settings(flat=499, threshold=5_000, tax_bps=2_000, included=True),
    )

    assert totals.shipping_minor == 0


def test_a_threshold_of_one_makes_any_paid_basket_ship_free() -> None:
    assert shipping_minor(1, settings(flat=499, threshold=1)) == 0


def test_a_basket_of_free_items_ships_free() -> None:
    totals = compute_totals([LineAmount(0, 2)], settings(flat=499))

    assert totals.shipping_minor == 0 and totals.total_minor == 0


def test_rejects_a_total_beyond_the_bigint_limit() -> None:
    with pytest.raises(ValueError, match="too large"):
        compute_totals([LineAmount(2**62, 3)], settings())
