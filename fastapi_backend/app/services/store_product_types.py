"""Limits, errors and data shapes of the product catalogue service (KAN-245)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from app.repositories.store_catalogue import ProductSummaryRow

STATUSES: Final = frozenset({"draft", "active"})
MAX_TITLE_LENGTH = 255
MAX_SLUG_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 10_000
MAX_NAME_LENGTH = 100  # option names, option values
MAX_SKU_LENGTH = 100
MAX_ALT_TEXT_LENGTH = 500
MAX_STORAGE_KEY_LENGTH = 255
MAX_OPTIONS = 3
MAX_VALUES_PER_OPTION = 50
MAX_VARIANTS = 100
MAX_CATEGORIES = 50
MAX_IMAGES = 20
# A bigint above 2^53 loses precision in JavaScript; weight and stock are int4 columns.
MAX_MINOR_UNITS = 2**53 - 1
MAX_WEIGHT_GRAMS = 1_000_000_000
MAX_STOCK = 1_000_000_000
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
MAX_OFFSET = 1_000_000
MAX_ID_LENGTH = 100


class CatalogueError(Exception):
    """Base class of catalogue errors; messages are safe to show to clients."""


class InvalidProduct(CatalogueError):
    """The input is not acceptable (422)."""


class CatalogueConflict(CatalogueError):
    """The change clashes with existing data, for example a taken SKU (409)."""


class ProductLimitReached(CatalogueError):
    """The plan allows no more products in this store; the message says to upgrade (409)."""


class ProductNotFound(CatalogueError):
    """No product has this id in this store (404)."""


class VariantNotFound(CatalogueError):
    """No variant has this id on this product (404)."""


class ImageNotFound(CatalogueError):
    """No image has this id on this product (404)."""


class Unset:
    """Marks a PATCH field the client did not send (``None`` is a real value)."""

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Final = Unset()


@dataclass(frozen=True)
class NewOption:
    name: str
    values: Sequence[str]


@dataclass(frozen=True)
class NewVariant:
    sku: str
    price_minor: int
    compare_at_price_minor: int | None = None
    weight_grams: int | None = None
    stock: int = 0
    options: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NewProduct:
    title: str
    variants: Sequence[NewVariant]
    slug: str | None = None
    description: str | None = None
    status: str = "draft"
    options: Sequence[NewOption] = ()
    category_ids: Sequence[str] = ()


@dataclass(frozen=True)
class ProductPatch:
    title: str | Unset = UNSET
    slug: str | Unset = UNSET
    description: str | None | Unset = UNSET
    status: str | Unset = UNSET
    category_ids: Sequence[str] | Unset = UNSET


@dataclass(frozen=True)
class VariantPatch:
    sku: str | Unset = UNSET
    price_minor: int | Unset = UNSET
    compare_at_price_minor: int | None | Unset = UNSET
    weight_grams: int | None | Unset = UNSET
    stock: int | Unset = UNSET


@dataclass(frozen=True)
class OptionValueRecord:
    id: str
    value: str
    position: int


@dataclass(frozen=True)
class OptionRecord:
    id: str
    name: str
    position: int
    values: tuple[OptionValueRecord, ...]


@dataclass(frozen=True)
class VariantChoiceRecord:
    option_id: str
    option_value_id: str


@dataclass(frozen=True)
class VariantRecord:
    id: str
    sku: str
    price_minor: int
    compare_at_price_minor: int | None
    weight_grams: int | None
    stock: int
    position: int
    option_values: tuple[VariantChoiceRecord, ...]


@dataclass(frozen=True)
class ImageRecord:
    id: str
    storage_key: str
    alt_text: str | None
    position: int


@dataclass(frozen=True)
class ProductRecord:
    id: str
    title: str
    slug: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    options: tuple[OptionRecord, ...]
    variants: tuple[VariantRecord, ...]
    category_ids: tuple[str, ...]
    images: tuple[ImageRecord, ...]


@dataclass(frozen=True)
class ProductPage:
    items: tuple[ProductSummaryRow, ...]
    total: int
    limit: int
    offset: int
