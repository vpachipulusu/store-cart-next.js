"""Server-side order totals: subtotal, shipping and tax in minor units (KAN-82, KAN-83).

Pure functions, no I/O: the caller loads ``TotalsSettings`` from the store settings and the
priced lines from the catalogue. Integer arithmetic only.

* **Shipping** is the flat rate, or 0 when a free-shipping threshold is set and the item
  subtotal (before any tax added on top) reaches it. An empty basket, or one whose items are all free (subtotal 0), ships nothing.
* **Tax** applies to the items, not to shipping, and is rounded half up per line, like
  ``store_orders.line_tax_minor``. When prices exclude tax it is added to the total; when
  prices include tax it is the part already inside the item prices and the total does not
  change (``subtotal + shipping``).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.services.store_orders import BPS_DENOMINATOR, MAX_MINOR, line_tax_minor


@dataclass(frozen=True)
class TotalsSettings:
    shipping_flat_rate_minor: int
    free_shipping_threshold_minor: int | None
    tax_rate_bps: int
    prices_include_tax: bool


@dataclass(frozen=True)
class LineAmount:
    unit_price_minor: int
    quantity: int


@dataclass(frozen=True)
class Totals:
    subtotal_minor: int
    shipping_minor: int
    tax_minor: int
    total_minor: int
    prices_include_tax: bool


def shipping_minor(subtotal_minor: int, settings: TotalsSettings) -> int:
    """Shipping for a basket whose item subtotal is ``subtotal_minor``."""
    if subtotal_minor <= 0:
        return 0
    threshold = settings.free_shipping_threshold_minor
    if threshold is not None and subtotal_minor >= threshold:
        return 0
    return settings.shipping_flat_rate_minor


def _included_tax_minor(gross_minor: int, tax_rate_bps: int) -> int:
    """The tax inside a tax-inclusive amount: gross minus the net, with the net rounded half up.

    So the tax itself rounds half down; net + tax always equals the gross.
    """
    divisor = BPS_DENOMINATOR + tax_rate_bps
    net = (gross_minor * BPS_DENOMINATOR + divisor // 2) // divisor
    return gross_minor - net


def line_tax(line: LineAmount, settings: TotalsSettings) -> int:
    """The tax of one line under the store's settings (added on top, or the part included)."""
    if settings.prices_include_tax:
        return _included_tax_minor(
            line.unit_price_minor * line.quantity, settings.tax_rate_bps
        )
    return line_tax_minor(line.unit_price_minor, line.quantity, settings.tax_rate_bps)


def compute_totals(lines: Sequence[LineAmount], settings: TotalsSettings) -> Totals:
    for line in lines:
        if line.unit_price_minor < 0 or line.quantity < 1:
            raise ValueError("A line needs a non-negative price and a quantity of 1+")
    subtotal = sum(line.unit_price_minor * line.quantity for line in lines)
    tax = sum(line_tax(line, settings) for line in lines)
    shipping = shipping_minor(subtotal, settings)
    added_tax = 0 if settings.prices_include_tax else tax
    total = subtotal + shipping + added_tax
    if total > MAX_MINOR:
        raise ValueError("The order total is too large")
    return Totals(
        subtotal_minor=subtotal,
        shipping_minor=shipping,
        tax_minor=tax,
        total_minor=total,
        prices_include_tax=settings.prices_include_tax,
    )
