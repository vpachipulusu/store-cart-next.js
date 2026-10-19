"""Product CSV import into one store (KAN-74). No FastAPI imports.

One row is one product with a single variant and no options; multi-variant products,
categories and images are edited in the dashboard afterwards. Columns (header names are
trimmed and matched without case; only ``title``, ``sku`` and ``price_minor`` are required):

``title, slug, description, status, sku, price_minor, compare_at_price_minor, weight_grams, stock``

Money is integer minor units, as everywhere in the catalogue API.

The import is all or nothing. Every row is checked first (cell rules, repeats inside the
file, slugs and SKUs already in the store, the plan's product limit); when any check fails
the result lists every failing cell by row and column and nothing is written. Otherwise
``StoreProductsService.create_many`` inserts every product in one store transaction, under
the same plan-limit lock as a single create, so a concurrent create or a rule the database
enforces (a SKU taken a moment ago) still rolls the whole file back.

Cells are checked with the same rules as the product API (``store_product_rules``), and
every text cell that starts with ``=``, ``+``, ``-``, ``@``, a tab or a carriage return is
refused: such a value would run as a formula when a merchant later opens an export in a
spreadsheet (CSV injection). The file must be UTF-8 (a byte order mark is allowed) and
is capped in bytes and rows.
"""

import csv
import io
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from app.services.plan_limits import UPGRADE_HINT
from app.services.store_product_rules import (
    CONFLICTS,
    clean_money,
    clean_optional_text,
    clean_slug,
    clean_status,
    clean_text,
    clean_variant,
    slugify,
)
from app.services.store_product_types import (
    MAX_DESCRIPTION_LENGTH,
    MAX_MINOR_UNITS,
    MAX_STOCK,
    MAX_TITLE_LENGTH,
    MAX_WEIGHT_GRAMS,
    CatalogueError,
    InvalidProduct,
    NewProduct,
    NewVariant,
    ProductLimitReached,
)

MAX_IMPORT_BYTES: Final = 1_000_000
MAX_IMPORT_ROWS: Final = 500
MAX_REPORTED_ERRORS: Final = 100

COLUMNS: Final = (
    "title",
    "slug",
    "description",
    "status",
    "sku",
    "price_minor",
    "compare_at_price_minor",
    "weight_grams",
    "stock",
)
REQUIRED_COLUMNS: Final = ("title", "sku", "price_minor")
TEXT_COLUMNS: Final = frozenset({"title", "slug", "description", "status", "sku"})

FORMULA_PREFIXES: Final = ("=", "+", "-", "@")
FORMULA_MESSAGE: Final = "Cell must not start with =, +, -, @, tab or carriage return"
NOT_UTF8_MESSAGE: Final = "The file must be UTF-8 encoded text"
_WHOLE_NUMBER: Final = re.compile(r"[0-9]{1,20}")


@dataclass(frozen=True)
class ImportIssue:
    """One problem. ``row`` is the spreadsheet row (header = 1); ``None`` for the file."""

    row: int | None
    column: str | None
    message: str


@dataclass(frozen=True)
class ParsedRow:
    row: int
    product: NewProduct


@dataclass(frozen=True)
class ParsedFile:
    rows: tuple[ParsedRow, ...]
    errors: tuple[ImportIssue, ...]
    truncated: bool = False


@dataclass(frozen=True)
class ImportResult:
    imported: int
    product_ids: tuple[str, ...]
    errors: tuple[ImportIssue, ...]
    truncated: bool = False


class ImportTarget(Protocol):
    """The parts of ``StoreProductsService`` the import uses."""

    async def product_capacity(self) -> int | None: ...

    async def taken_slugs_and_skus(
        self, slugs: Sequence[str], skus: Sequence[str]
    ) -> tuple[set[str], set[str]]: ...

    async def create_many(self, products: Sequence[NewProduct]) -> tuple[str, ...]: ...


class _FileError(Exception):
    """The file as a whole cannot be imported; the message is shown as it is."""


# --- cells ----------------------------------------------------------------------------


# Zero-width characters a spreadsheet may ignore in front of a formula.
_INVISIBLE: Final = "\u200b‌‍⁠﻿"


def _is_formula(value: str) -> bool:
    if value[:1] in ("\t", "\r"):
        return True
    return value.lstrip().lstrip(_INVISIBLE).lstrip().startswith(FORMULA_PREFIXES)


def _whole_number(value: str, label: str, upper: int) -> int:
    if _WHOLE_NUMBER.fullmatch(value) is None:
        raise InvalidProduct(f"{label} must be a whole number")
    number = int(value)
    if number > upper:
        raise InvalidProduct(f"{label} must be between 0 and {upper}")
    return number


class _RowChecker:
    """Checks one row cell by cell, collecting every error instead of stopping at one."""

    def __init__(self, row: int, cells: dict[str, str]) -> None:
        self.row = row
        self.cells = cells
        self.errors: list[ImportIssue] = []

    def fail(self, column: str, message: str) -> None:
        self.errors.append(ImportIssue(self.row, column, message))

    def cell(self, column: str) -> str | None:
        """The trimmed cell, or ``None`` after recording a formula error."""
        raw = self.cells.get(column, "")
        if column in TEXT_COLUMNS and _is_formula(raw):
            self.fail(column, FORMULA_MESSAGE)
            return None
        return raw.strip()

    def title(self) -> str | None:
        value = self.cell("title")
        if value is None:
            return None
        try:
            return clean_text(value, "Title", MAX_TITLE_LENGTH)
        except InvalidProduct as error:
            self.fail("title", str(error))
            return None

    def slug(self, title: str | None) -> str | None:
        value = self.cell("slug")
        if value is None:
            return None
        if value:
            try:
                return clean_slug(value)
            except InvalidProduct as error:
                self.fail("slug", str(error))
                return None
        if title is None:
            return None  # the title error is enough
        derived = slugify(title)
        if not derived:
            self.fail("slug", "Provide a slug: the title has no usable characters")
            return None
        return derived

    def description(self) -> str | None:
        value = self.cell("description")
        if not value:
            return None
        try:
            return clean_optional_text(value, "Description", MAX_DESCRIPTION_LENGTH)
        except InvalidProduct as error:
            self.fail("description", str(error))
            return None

    def status(self) -> str | None:
        value = self.cell("status")
        if value is None:
            return None
        try:
            return clean_status(value.lower() or "draft")
        except InvalidProduct as error:
            self.fail("status", str(error))
            return None

    def sku(self) -> str | None:
        value = self.cell("sku")
        if value is None:
            return None
        try:
            return clean_variant(NewVariant(sku=value, price_minor=0), {}).sku
        except InvalidProduct as error:
            self.fail("sku", str(error))
            return None

    def number(self, column: str, label: str, upper: int) -> int | None:
        value = self.cell(column) or ""
        if value == "":
            return None
        try:
            return _whole_number(value, label, upper)
        except InvalidProduct as error:
            self.fail(column, str(error))
            return None

    def price(self) -> int | None:
        if (self.cell("price_minor") or "") == "":
            self.fail("price_minor", "Price is required")
            return None
        return self.number("price_minor", "Price", MAX_MINOR_UNITS)

    def compare_at(self, price: int | None) -> int | None:
        failed = len(self.errors)
        value = self.number(
            "compare_at_price_minor", "Compare-at price", MAX_MINOR_UNITS
        )
        if value is None or price is None or len(self.errors) > failed:
            return value
        try:
            return clean_money(price, value).compare_at_price_minor
        except InvalidProduct as error:
            self.fail("compare_at_price_minor", str(error))
            return None


def _check_row(
    row: int, cells: dict[str, str]
) -> tuple[NewProduct | None, list[ImportIssue]]:
    check = _RowChecker(row, cells)
    title = check.title()
    slug = check.slug(title)
    description = check.description()
    status = check.status()
    sku = check.sku()
    price = check.price()
    compare_at = check.compare_at(price)
    weight = check.number("weight_grams", "Weight", MAX_WEIGHT_GRAMS)
    stock = check.number("stock", "Stock", MAX_STOCK)
    # Without errors every required cell has a value; the None checks narrow the types.
    if (
        check.errors
        or title is None
        or slug is None
        or status is None
        or sku is None
        or price is None
    ):
        return None, check.errors
    variant = NewVariant(
        sku=sku,
        price_minor=price,
        compare_at_price_minor=compare_at,
        weight_grams=weight,
        stock=stock or 0,
    )
    product = NewProduct(
        title=title,
        slug=slug,
        description=description,
        status=status,
        variants=(variant,),
    )
    return product, []


# --- the file -------------------------------------------------------------------------


def _decode(content: bytes) -> str:
    if len(content) > MAX_IMPORT_BYTES:
        raise _FileError(f"The file is larger than {MAX_IMPORT_BYTES // 1000} KB")
    if not content:
        raise _FileError("The file is empty")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _FileError(NOT_UTF8_MESSAGE) from None
    if "\x00" in text:
        raise _FileError(NOT_UTF8_MESSAGE)
    return text


def _header(names: list[str]) -> list[str]:
    header = [name.strip().lower() for name in names]
    seen: set[str] = set()
    for name in header:
        if not name:
            raise _FileError("A column has no name")
        if name not in COLUMNS:
            raise _FileError(f"Unknown column: {name[:40]}")
        if name in seen:
            raise _FileError(f"Column {name} appears twice")
        seen.add(name)
    for name in REQUIRED_COLUMNS:
        if name not in seen:
            raise _FileError(f"Missing column: {name}")
    return header


def _records(text: str) -> Iterator[tuple[int, list[str]]]:
    """The header as row 1, then (spreadsheet row, cells) of every non-blank record."""
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        names = next(reader, None)
        if names is None:
            raise _FileError("The file is empty")
        if not any(name.strip() for name in names):
            raise _FileError("The first row must be the column names")
        yield 1, names
        for number, cells in enumerate(reader, start=2):
            if any(cell.strip() for cell in cells):
                yield number, cells
    except csv.Error:
        raise _FileError(
            f"The file is not valid CSV near line {reader.line_num}"
        ) from None


class _Duplicates:
    """First row that used each slug and SKU (SKUs compare without case)."""

    def __init__(self) -> None:
        self.slugs: dict[str, int] = {}
        self.skus: dict[str, int] = {}

    def check(self, row: int, product: NewProduct) -> list[ImportIssue]:
        errors: list[ImportIssue] = []
        slug = product.slug or ""
        sku = product.variants[0].sku.lower()
        if slug in self.slugs:
            errors.append(
                ImportIssue(row, "slug", f"Slug repeats row {self.slugs[slug]}")
            )
        else:
            self.slugs[slug] = row
        if sku in self.skus:
            errors.append(ImportIssue(row, "sku", f"SKU repeats row {self.skus[sku]}"))
        else:
            self.skus[sku] = row
        return errors


def _file_error(message: str) -> ParsedFile:
    return ParsedFile((), (ImportIssue(None, None, message),))


def _width_error(number: int, cells: list[str], header: list[str]) -> ImportIssue:
    return ImportIssue(
        number, None, f"Row has {len(cells)} cells; the header has {len(header)}"
    )


def parse_products_csv(content: bytes) -> ParsedFile:
    """Every product row of the file, or every problem found (then ``rows`` is empty)."""
    rows: list[ParsedRow] = []
    errors: list[ImportIssue] = []
    duplicates = _Duplicates()
    try:
        records = _records(_decode(content))
        header = _header(next(records)[1])
        for count, (number, cells) in enumerate(records, start=1):
            if count > MAX_IMPORT_ROWS:
                raise _FileError(
                    f"The file has more than {MAX_IMPORT_ROWS} product rows"
                )
            if len(cells) != len(header):
                errors.append(_width_error(number, cells, header))
                continue
            product, row_errors = _check_row(
                number, dict(zip(header, cells, strict=True))
            )
            if product is not None:
                row_errors = duplicates.check(number, product)
            errors.extend(row_errors)
            if product is not None and not row_errors:
                rows.append(ParsedRow(number, product))
    except _FileError as error:
        return _file_error(str(error))
    if errors:
        truncated = len(errors) > MAX_REPORTED_ERRORS
        return ParsedFile((), tuple(errors[:MAX_REPORTED_ERRORS]), truncated)
    if not rows:
        return _file_error("The file has no product rows")
    return ParsedFile(tuple(rows), ())


# --- the import -----------------------------------------------------------------------


def _rejected(errors: Sequence[ImportIssue], truncated: bool = False) -> ImportResult:
    return ImportResult(0, (), tuple(errors), truncated)


def _capacity_message(capacity: int, rows: int) -> str:
    noun = "product" if capacity == 1 else "products"
    return (
        f"The store has room for {capacity} more {noun} on its plan; "
        f"the file has {rows}. {UPGRADE_HINT}"
    )


async def _store_conflicts(
    target: ImportTarget, rows: Sequence[ParsedRow]
) -> list[ImportIssue]:
    slugs, skus = await target.taken_slugs_and_skus(
        [r.product.slug or "" for r in rows], [r.product.variants[0].sku for r in rows]
    )
    errors: list[ImportIssue] = []
    for parsed in rows:
        if parsed.product.slug in slugs:
            errors.append(
                ImportIssue(parsed.row, "slug", CONFLICTS["uq_products_slug"])
            )
        if parsed.product.variants[0].sku.lower() in skus:
            errors.append(
                ImportIssue(parsed.row, "sku", CONFLICTS["uq_variants_sku_lower"])
            )
    return errors


async def import_products(target: ImportTarget, content: bytes) -> ImportResult:
    """Import every row of ``content`` into the target store, or none of them."""
    parsed = parse_products_csv(content)
    if parsed.errors:
        return _rejected(parsed.errors, parsed.truncated)
    capacity = await target.product_capacity()
    if capacity is not None and len(parsed.rows) > capacity:
        return _rejected(
            [ImportIssue(None, None, _capacity_message(capacity, len(parsed.rows)))]
        )
    conflicts = await _store_conflicts(target, parsed.rows)
    if conflicts:
        return _rejected(
            conflicts[:MAX_REPORTED_ERRORS], len(conflicts) > MAX_REPORTED_ERRORS
        )
    try:
        ids = await target.create_many([r.product for r in parsed.rows])
    except ProductLimitReached as error:
        return _rejected([ImportIssue(None, None, str(error))])
    except CatalogueError as error:
        # A race the pre-checks could not see (a SKU taken a moment ago): the database
        # does not say which row, so the whole file is reported.
        return _rejected([ImportIssue(None, None, f"Nothing was imported: {error}")])
    return ImportResult(len(ids), ids, ())
