"""Product CSV import (KAN-74) without a database: parsing, per-row errors and the write step."""

import csv
from collections.abc import Sequence
from typing import Any

import pytest

from app.core.plans import PLANS, Plan, PlanKey
from app.services.product_import import (
    COLUMNS,
    MAX_IMPORT_BYTES,
    MAX_IMPORT_ROWS,
    MAX_REPORTED_ERRORS,
    import_products,
    parse_products_csv,
)
from app.services.store_product_types import (
    CatalogueConflict,
    NewProduct,
    ProductLimitReached,
)
from app.services.store_products import (
    IMPORT_LOCK_TIMEOUT_MS,
    IMPORT_STATEMENT_TIMEOUT_MS,
    StoreProductsService,
)

HEADER = ",".join(COLUMNS)


def csv_of(*rows: str, header: str = HEADER) -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode()


def row(
    title: str = "Mug",
    slug: str = "",
    description: str = "",
    status: str = "",
    sku: str = "MUG-1",
    price: str = "1999",
    compare_at: str = "",
    weight: str = "",
    stock: str = "",
) -> str:
    cells = [title, slug, description, status, sku, price, compare_at, weight, stock]
    return ",".join(cells)


def errors_of(content: bytes) -> list[tuple[int | None, str | None, str]]:
    return [(e.row, e.column, e.message) for e in parse_products_csv(content).errors]


# --- valid files ------------------------------------------------------------------


def test_a_valid_row_becomes_a_single_variant_product() -> None:
    parsed = parse_products_csv(
        csv_of(
            row(
                "Blue Mug",
                "",
                "Stoneware",
                "active",
                "MUG-1",
                "1999",
                "2499",
                "350",
                "12",
            )
        )
    )

    assert parsed.errors == ()
    assert len(parsed.rows) == 1
    parsed_row = parsed.rows[0]
    assert parsed_row.row == 2  # the header is row 1, as in a spreadsheet
    product = parsed_row.product
    assert (product.title, product.slug, product.description, product.status) == (
        "Blue Mug",
        "blue-mug",
        "Stoneware",
        "active",
    )
    assert product.options == ()
    assert product.category_ids == ()
    variant = product.variants[0]
    assert (
        variant.sku,
        variant.price_minor,
        variant.compare_at_price_minor,
        variant.weight_grams,
        variant.stock,
    ) == ("MUG-1", 1999, 2499, 350, 12)


def test_optional_cells_take_defaults_and_header_case_and_bom_are_ignored() -> None:
    content = "﻿" + "Title , SKU,Price_Minor\nPlate,PL-1,500\n"

    parsed = parse_products_csv(content.encode())

    assert parsed.errors == ()
    product = parsed.rows[0].product
    assert (product.slug, product.description, product.status) == (
        "plate",
        None,
        "draft",
    )
    assert (product.variants[0].stock, product.variants[0].weight_grams) == (0, None)


def test_blank_lines_are_skipped_but_still_counted() -> None:
    parsed = parse_products_csv(
        csv_of(row(sku="A-1"), ",,,,,,,,", "", row("Cup", sku="A-2"))
    )

    assert parsed.errors == ()
    assert [r.row for r in parsed.rows] == [2, 5]


def test_quoted_cells_keep_commas_and_newlines() -> None:
    parsed = parse_products_csv(
        csv_of('"Mug, large",,"Line one\nline two",,M-1,100,,,')
    )

    assert parsed.errors == ()
    assert parsed.rows[0].product.title == "Mug, large"
    assert parsed.rows[0].product.description == "Line one\nline two"


# --- per-row errors ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("cells", "column", "fragment"),
    [
        ({"title": ""}, "title", "Title must not be blank"),
        ({"sku": ""}, "sku", "SKU must not be blank"),
        ({"price": ""}, "price_minor", "Price is required"),
        ({"price": "19.99"}, "price_minor", "whole number"),
        ({"price": "abc"}, "price_minor", "whole number"),
        ({"price": str(2**53)}, "price_minor", "between 0 and"),
        ({"stock": "-1"}, "stock", "whole number"),
        ({"weight": "1e3"}, "weight_grams", "whole number"),
        (
            {"compare_at": "100", "price": "200"},
            "compare_at_price_minor",
            "above the price",
        ),
        ({"status": "archived"}, "status", "draft or active"),
        ({"slug": "Not A Slug"}, "slug", "lower-case letters"),
        ({"title": "!!!"}, "slug", "Provide a slug"),
    ],
)
def test_an_invalid_cell_is_reported_with_its_row_and_column(
    cells: dict[str, str], column: str, fragment: str
) -> None:
    errors = errors_of(csv_of(row(sku="OK-1"), row(**cells)))

    assert len(errors) == 1
    assert errors[0][:2] == (3, column)
    assert fragment in errors[0][2]


FORMULA_MESSAGE = "Cell must not start with =, +, -, @, tab or carriage return"


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r", " =", "\u200b="])
def test_formula_leading_text_cells_are_rejected(prefix: str) -> None:
    cell = f'"{prefix}HYPERLINK(""http://x"")"'
    errors = errors_of(csv_of(row(title=cell)))

    assert errors == [(2, "title", FORMULA_MESSAGE)]


def test_formula_check_covers_every_text_column() -> None:
    errors = errors_of(
        csv_of(row(description="=1+1", sku="@SUM(A1)", slug="+x", status="-draft"))
    )

    assert {column for _, column, _ in errors} == {
        "description",
        "sku",
        "slug",
        "status",
    }


def test_every_failing_row_is_reported_not_just_the_first() -> None:
    errors = errors_of(csv_of(row(title=""), row(sku="B-1"), row(price="x", sku="C-1")))

    assert [(r, c) for r, c, _ in errors] == [(2, "title"), (4, "price_minor")]


def test_several_bad_cells_in_one_row_are_all_reported() -> None:
    errors = errors_of(csv_of(row(title="", price="x", stock="y")))

    assert [c for _, c, _ in errors] == ["title", "price_minor", "stock"]


def test_a_row_with_the_wrong_number_of_cells_is_reported() -> None:
    errors = errors_of(csv_of("Mug,,,,M-1,100"))

    assert errors == [(2, None, "Row has 6 cells; the header has 9")]


def test_duplicate_skus_and_slugs_in_the_file_name_the_first_row() -> None:
    errors = errors_of(
        csv_of(row("Mug", sku="M-1"), row("Cup", sku="m-1"), row("Mug", sku="M-2"))
    )

    assert errors == [
        (3, "sku", "SKU repeats row 2"),
        (4, "slug", "Slug repeats row 2"),
    ]


def test_reported_errors_are_capped() -> None:
    rows = [row(title="", sku=f"S-{n}") for n in range(MAX_REPORTED_ERRORS + 5)]

    parsed = parse_products_csv(csv_of(*rows))

    assert len(parsed.errors) == MAX_REPORTED_ERRORS
    assert parsed.truncated is True


# --- file errors ------------------------------------------------------------------

NOT_UTF8 = "The file must be UTF-8 encoded text"


def test_non_utf8_is_a_file_error() -> None:
    content = HEADER.encode() + b"\nCaf\xe9,,,,C-1,100,,,\n"

    assert errors_of(content) == [(None, None, NOT_UTF8)]


def test_nul_bytes_are_a_file_error() -> None:
    assert errors_of(csv_of(row(title="Mu\x00g"))) == [(None, None, NOT_UTF8)]


def test_an_empty_file_is_a_file_error() -> None:
    assert errors_of(b"") == [(None, None, "The file is empty")]


def test_a_file_without_rows_is_a_file_error() -> None:
    assert errors_of(csv_of()) == [(None, None, "The file has no product rows")]


def test_a_file_over_the_byte_cap_is_refused() -> None:
    content = csv_of(row(description="x" * (MAX_IMPORT_BYTES + 1)))

    assert errors_of(content) == [(None, None, "The file is larger than 1 MB")]


def test_a_file_over_the_row_cap_is_refused() -> None:
    rows = [row(f"Mug {n}", sku=f"M-{n}") for n in range(MAX_IMPORT_ROWS + 1)]

    assert errors_of(csv_of(*rows)) == [
        (None, None, f"The file has more than {MAX_IMPORT_ROWS} product rows")
    ]


@pytest.mark.parametrize(
    ("header", "message"),
    [
        ("title,sku", "Missing column: price_minor"),
        ("title,sku,price_minor,colour", "Unknown column: colour"),
        ("title,sku,price_minor,sku", "Column sku appears twice"),
        ("title,,sku,price_minor", "A column has no name"),
        ("=title,sku,price_minor", "Unknown column: =title"),
    ],
)
def test_header_problems_are_file_errors(header: str, message: str) -> None:
    assert errors_of(csv_of("x", header=header)) == [(None, None, message)]


def test_a_malformed_quote_is_a_file_error() -> None:
    content = csv_of('Mug,,"open,,M-1,100,,,', 'Cup,,,,"bad"x,100,,,')

    errors = errors_of(content)

    assert len(errors) == 1
    assert errors[0][0] is None


# --- the write step ---------------------------------------------------------------


class FakeService:
    def __init__(
        self,
        *,
        taken_slugs: set[str] | None = None,
        taken_skus: set[str] | None = None,
        capacity: int | None = None,
        fail: Exception | None = None,
    ) -> None:
        self.taken_slugs = taken_slugs or set()
        self.taken_skus = taken_skus or set()
        self.capacity = capacity
        self.fail = fail
        self.created: list[NewProduct] = []

    async def taken_slugs_and_skus(
        self, slugs: Sequence[str], skus: Sequence[str]
    ) -> tuple[set[str], set[str]]:
        return (
            {s for s in slugs if s in self.taken_slugs},
            {s.lower() for s in skus if s.lower() in self.taken_skus},
        )

    async def product_capacity(self) -> int | None:
        return self.capacity

    async def create_many(self, products: Sequence[NewProduct]) -> tuple[str, ...]:
        if self.fail is not None:
            raise self.fail
        self.created.extend(products)
        return tuple(f"id-{n}" for n in range(len(products)))


async def run(service: FakeService, content: bytes):  # type: ignore[no-untyped-def]
    return await import_products(service, content)  # type: ignore[arg-type]


async def test_a_valid_file_is_written_in_one_call() -> None:
    service = FakeService()

    result = await run(service, csv_of(row(sku="A"), row("Cup", sku="B")))

    assert result.errors == ()
    assert result.imported == 2
    assert result.product_ids == ("id-0", "id-1")
    assert [p.title for p in service.created] == ["Mug", "Cup"]


async def test_nothing_is_written_when_any_row_fails() -> None:
    service = FakeService()

    result = await run(service, csv_of(row(sku="A"), row(title="", sku="B")))

    assert result.imported == 0
    assert result.product_ids == ()
    assert [(e.row, e.column) for e in result.errors] == [(3, "title")]
    assert service.created == []


async def test_slugs_and_skus_already_in_the_store_are_row_errors() -> None:
    service = FakeService(taken_slugs={"cup"}, taken_skus={"a-1"})

    result = await run(service, csv_of(row("Mug", sku="A-1"), row("Cup", sku="B-1")))

    assert [(e.row, e.column, e.message) for e in result.errors] == [
        (2, "sku", "SKU is already in use"),
        (3, "slug", "Slug is already in use"),
    ]
    assert service.created == []


async def test_more_rows_than_the_plan_allows_is_a_file_error() -> None:
    service = FakeService(capacity=1)

    result = await run(service, csv_of(row(sku="A"), row("Cup", sku="B")))

    assert result.imported == 0
    assert len(result.errors) == 1
    error = result.errors[0]
    assert (error.row, error.column) == (None, None)
    assert "room for 1 more product" in error.message
    assert "Upgrade" in error.message
    assert service.created == []


async def test_a_limit_hit_during_the_write_is_a_file_error() -> None:
    service = FakeService(fail=ProductLimitReached("The Free plan allows 25 products"))

    result = await run(service, csv_of(row()))

    assert [(e.row, e.message) for e in result.errors] == [
        (None, "The Free plan allows 25 products")
    ]


async def test_a_conflict_during_the_write_is_a_file_error() -> None:
    service = FakeService(fail=CatalogueConflict("SKU is already in use"))

    result = await run(service, csv_of(row()))

    assert [(e.row, e.message) for e in result.errors] == [
        (None, "Nothing was imported: SKU is already in use")
    ]


def test_a_blank_first_line_is_not_taken_as_the_header() -> None:
    assert errors_of(b"\n" + csv_of(row())) == [
        (None, None, "The first row must be the column names")
    ]


def test_crlf_line_endings_parse_like_lf() -> None:
    content = csv_of(row(sku="A"), row("Cup", sku="B")).replace(b"\n", b"\r\n")

    parsed = parse_products_csv(content)

    assert parsed.errors == ()
    assert [r.row for r in parsed.rows] == [2, 3]


def test_a_quoted_newline_does_not_shift_later_row_numbers() -> None:
    content = csv_of('"Mug",,"two\nlines",,M-1,100,,,', row(title="", sku="M-2"))

    assert [(r, c) for r, c, _ in errors_of(content)] == [(3, "title")]


def test_exactly_the_row_cap_is_accepted() -> None:
    rows = [row(f"Mug {n}", sku=f"M-{n}") for n in range(MAX_IMPORT_ROWS)]

    assert len(parse_products_csv(csv_of(*rows)).rows) == MAX_IMPORT_ROWS


async def test_create_many_of_nothing_writes_nothing() -> None:
    async def plan() -> Plan:
        raise AssertionError("no plan lookup for an empty batch")

    service = StoreProductsService(None, None, "store", plan)  # type: ignore[arg-type]

    assert await service.create_many([]) == ()


class RecordingRepository:
    """Records the calls ``create_many`` makes; reads return fixed values."""

    def __init__(self) -> None:
        self.events: list[str] = []

    async def set_transaction_timeouts(
        self, *, statement_ms: int, lock_ms: int
    ) -> None:
        self.events.append(f"timeouts {statement_ms} {lock_ms}")

    async def count_all_products(self) -> int:
        self.events.append("count")
        return 0

    def __getattr__(self, name: str) -> Any:
        async def record(*args: object, **kwargs: object) -> None:
            self.events.append(name)

        return record


class RecordingSession:
    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


async def test_create_many_bounds_the_transaction_before_taking_the_lock() -> None:
    repository = RecordingRepository()

    async def plan() -> Plan:
        return PLANS[PlanKey.FREE]

    service = StoreProductsService(repository, RecordingSession(), "store", plan)  # type: ignore[arg-type]
    products = [p.product for p in parse_products_csv(csv_of(row())).rows]

    ids = await service.create_many(products)

    assert len(ids) == 1
    assert repository.events[:3] == [
        f"timeouts {IMPORT_STATEMENT_TIMEOUT_MS} {IMPORT_LOCK_TIMEOUT_MS}",
        "lock_catalogue",
        "count",
    ]
    # A new product without categories has no links to replace.
    assert "replace_categories" not in repository.events


def test_a_cell_over_the_csv_field_limit_is_a_file_error() -> None:
    errors = errors_of(csv_of(row(description="x" * (csv.field_size_limit() + 1))))

    assert len(errors) == 1
    assert errors[0][:2] == (None, None)
    assert "not valid CSV" in errors[0][2]


def test_an_over_long_description_is_a_description_error() -> None:
    errors = errors_of(csv_of(row(description="x" * 10_001)))

    assert [(r, c) for r, c, _ in errors] == [(2, "description")]
