"""Validation and catalogue rules of the product service (KAN-245). Pure functions, no I/O.

Text is trimmed and checked for
control characters, numbers are range-checked before they reach an ``int`` column.
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from sqlalchemy.exc import DataError, DBAPIError, IntegrityError

from app.repositories.store_catalogue import (
    ImageRow,
    OptionRow,
    OptionValueRow,
    VariantChoice,
    VariantRow,
)
from app.services.store_product_types import (
    MAX_CATEGORIES,
    MAX_ID_LENGTH,
    MAX_MINOR_UNITS,
    MAX_NAME_LENGTH,
    MAX_OPTIONS,
    MAX_SKU_LENGTH,
    MAX_SLUG_LENGTH,
    MAX_STOCK,
    MAX_STORAGE_KEY_LENGTH,
    MAX_VALUES_PER_OPTION,
    MAX_WEIGHT_GRAMS,
    STATUSES,
    CatalogueConflict,
    CatalogueError,
    ImageRecord,
    InvalidProduct,
    NewOption,
    NewVariant,
    OptionRecord,
    OptionValueRecord,
    Unset,
    VariantChoiceRecord,
    VariantPatch,
    VariantRecord,
)

SLUG_PATTERN = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
IMAGE_FILE_PATTERN = re.compile(r"[A-Za-z0-9_-]+[.](jpg|png|webp)")

# Constraint names from store revisions 0002 and 0003 mapped to fixed client messages.
CONFLICTS: Final = {
    "uq_products_slug": "Slug is already in use",
    "uq_variants_sku_lower": "SKU is already in use",
    "uq_product_images_storage_key": "Image is already attached",
    "uq_product_images_product_position": "Image order changed, retry",
    "uq_product_options_product_name": "Option names must be unique",
    "uq_product_option_values_option_value": "Option values must be unique",
}


# --- validation --------------------------------------------------------------------


def _unencodable(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False


def _has_control_character(value: str) -> bool:
    return any(unicodedata.category(char) == "Cc" for char in value)


def clean_text(value: object, label: str, max_length: int) -> str:
    """A trimmed, non-blank string without control characters, at most ``max_length``."""
    if not isinstance(value, str):
        raise InvalidProduct(f"{label} must be text")
    cleaned = value.strip()
    if not cleaned:
        raise InvalidProduct(f"{label} must not be blank")
    if len(cleaned) > max_length:
        raise InvalidProduct(f"{label} must be at most {max_length} characters")
    if _has_control_character(cleaned) or _unencodable(cleaned):
        raise InvalidProduct(f"{label} must not contain control characters")
    return cleaned


def clean_optional_text(value: object, label: str, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidProduct(f"{label} must be text")
    if len(value) > max_length:
        raise InvalidProduct(f"{label} must be at most {max_length} characters")
    if "\x00" in value or _unencodable(value):
        raise InvalidProduct(f"{label} must not contain control characters")
    return value


def _integer(value: object, label: str, upper: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidProduct(f"{label} must be a whole number")
    if not 0 <= value <= upper:
        raise InvalidProduct(f"{label} must be between 0 and {upper}")
    return value


def slugify(title: str) -> str:
    """Lower-case hyphenated ASCII form of ``title`` (empty when nothing survives)."""
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    hyphenated = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return hyphenated[:MAX_SLUG_LENGTH].strip("-")


def clean_slug(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) > MAX_SLUG_LENGTH
        or SLUG_PATTERN.fullmatch(value) is None
    ):
        raise InvalidProduct(
            "Slug must be lower-case letters and digits separated by single hyphens"
        )
    return value


def clean_status(value: object) -> str:
    if not isinstance(value, str) or value not in STATUSES:
        raise InvalidProduct("Status must be draft or active")
    return value


def _sku(value: object) -> str:
    cleaned = clean_text(value, "SKU", MAX_SKU_LENGTH)
    # Invisible format characters would make look-alike SKUs that dodge the unique index.
    if any(unicodedata.category(char) == "Cf" for char in cleaned):
        raise InvalidProduct("SKU must not contain invisible characters")
    return cleaned


def clean_category_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise InvalidProduct("Categories must be a list")
    if len(value) > MAX_CATEGORIES:
        raise InvalidProduct(f"A product has at most {MAX_CATEGORIES} categories")
    cleaned: list[str] = []
    for category_id in value:
        if (
            not isinstance(category_id, str)
            or not 1 <= len(category_id) <= MAX_ID_LENGTH
            or "\x00" in category_id
        ):
            raise InvalidProduct("Unknown category")
        if category_id not in cleaned:
            cleaned.append(category_id)
    return tuple(cleaned)


@dataclass(frozen=True)
class _Money:
    price_minor: int
    compare_at_price_minor: int | None


def clean_money(price: object, compare_at: object) -> _Money:
    cleaned_price = _integer(price, "Price", MAX_MINOR_UNITS)
    if compare_at is None:
        return _Money(cleaned_price, None)
    cleaned_compare_at = _integer(compare_at, "Compare-at price", MAX_MINOR_UNITS)
    if cleaned_compare_at == cleaned_price:
        return _Money(cleaned_price, None)  # equal means no sale
    if cleaned_compare_at < cleaned_price:
        raise InvalidProduct("Compare-at price must be above the price")
    return _Money(cleaned_price, cleaned_compare_at)


def _weight(value: object) -> int | None:
    return None if value is None else _integer(value, "Weight", MAX_WEIGHT_GRAMS)


def image_key_for_store(store_id: str, value: object) -> str:
    """``value`` when it is an object key under ``stores/{store_id}/``, else ``InvalidProduct``.

    The prefix is the store the caller's membership resolved, never client input; the rest
    must match ``ck_product_images_storage_key`` (one path segment, an allowed extension).
    """
    prefix = f"stores/{store_id}/"
    if (
        not isinstance(value, str)
        or len(value) > MAX_STORAGE_KEY_LENGTH
        or not value.startswith(prefix)
        or IMAGE_FILE_PATTERN.fullmatch(value[len(prefix) :]) is None
    ):
        raise InvalidProduct("Image key does not belong to this store")
    return value


def _constraint_name(error: IntegrityError | DataError) -> str | None:
    original = error.orig
    for candidate in (original, getattr(original, "__cause__", None)):
        name = getattr(candidate, "constraint_name", None)
        if isinstance(name, str):
            return name
    return None


# Deadlock, serialization failure and lock timeout.
RETRYABLE_SQLSTATES: Final = frozenset({"40P01", "40001", "55P03"})


def is_retryable(error: DBAPIError) -> bool:
    """Nothing is wrong with the input: the client may simply retry."""
    original = error.orig
    for candidate in (original, getattr(original, "__cause__", None)):
        if getattr(candidate, "sqlstate", None) in RETRYABLE_SQLSTATES:
            return True
    return False


def translate_error(error: IntegrityError | DataError) -> CatalogueError | None:
    name = _constraint_name(error) or ""
    if name in CONFLICTS:
        return CatalogueConflict(CONFLICTS[name])
    if isinstance(error, DataError) or name.startswith(("ck_", "fk_")):
        return InvalidProduct("The product data is not valid")
    return None


# --- option and variant rules --------------------------------------------------------

OptionLookup = Mapping[str, Mapping[str, tuple[str, str]]]


def clean_options(options: Sequence[NewOption]) -> list[tuple[str, list[str]]]:
    if len(options) > MAX_OPTIONS:
        raise InvalidProduct(f"A product has at most {MAX_OPTIONS} options")
    cleaned: list[tuple[str, list[str]]] = []
    names: set[str] = set()
    for option in options:
        name = clean_text(option.name, "Option name", MAX_NAME_LENGTH)
        if name.lower() in names:
            raise InvalidProduct("Option names must be unique")
        names.add(name.lower())
        if not 1 <= len(option.values) <= MAX_VALUES_PER_OPTION:
            raise InvalidProduct(f"An option has 1 to {MAX_VALUES_PER_OPTION} values")
        values = [clean_text(v, "Option value", MAX_NAME_LENGTH) for v in option.values]
        if len({v.lower() for v in values}) != len(values):
            raise InvalidProduct("Option values must be unique")
        cleaned.append((name, values))
    return cleaned


def _resolve_choices(
    chosen: Mapping[str, str], options: OptionLookup
) -> dict[str, str]:
    """Option id to value id for one variant, or ``InvalidProduct``.

    ``options`` maps lower-cased option name to ``{lower-cased value: (option id, value id)}``.
    """
    picked = {name.lower(): value for name, value in chosen.items()}
    if len(picked) != len(chosen) or set(picked) != set(options):
        raise InvalidProduct("A variant must choose one value for every option")
    resolved: dict[str, str] = {}
    for name, value in picked.items():
        if not isinstance(value, str):
            raise InvalidProduct("Option values must be text")
        match = options[name].get(value.strip().lower())
        if match is None:
            raise InvalidProduct("A variant chose a value its option does not have")
        resolved[match[0]] = match[1]
    return resolved


@dataclass(frozen=True)
class CleanVariant:
    sku: str
    money: _Money
    weight_grams: int | None
    stock: int
    choices: dict[str, str]  # option id -> value id

    @property
    def combination(self) -> frozenset[tuple[str, str]]:
        return frozenset(self.choices.items())


def clean_variant(variant: NewVariant, options: OptionLookup) -> CleanVariant:
    return CleanVariant(
        sku=_sku(variant.sku),
        money=clean_money(variant.price_minor, variant.compare_at_price_minor),
        weight_grams=_weight(variant.weight_grams),
        stock=_integer(variant.stock, "Stock", MAX_STOCK),
        choices=_resolve_choices(variant.options, options),
    )


def option_lookup(
    options: Sequence[OptionRow], values: Sequence[OptionValueRow]
) -> dict[str, dict[str, tuple[str, str]]]:
    by_option: dict[str, dict[str, tuple[str, str]]] = {o.id: {} for o in options}
    for value in values:
        by_option[value.option_id][value.value.lower()] = (value.option_id, value.id)
    return {o.name.lower(): by_option[o.id] for o in options}


def variant_changes(current: VariantRow, patch: VariantPatch) -> dict[str, object]:
    changes: dict[str, object] = {}
    if not isinstance(patch.sku, Unset):
        changes["sku"] = _sku(patch.sku)
    if not isinstance(patch.stock, Unset):
        changes["stock"] = _integer(patch.stock, "Stock", MAX_STOCK)
    if not isinstance(patch.weight_grams, Unset):
        changes["weight_grams"] = _weight(patch.weight_grams)
    if isinstance(patch.price_minor, Unset) and isinstance(
        patch.compare_at_price_minor, Unset
    ):
        return changes
    price = (
        current.price_minor
        if isinstance(patch.price_minor, Unset)
        else patch.price_minor
    )
    compare_at = (
        current.compare_at_price_minor
        if isinstance(patch.compare_at_price_minor, Unset)
        else patch.compare_at_price_minor
    )
    money = clean_money(price, compare_at)
    changes["price_minor"] = money.price_minor
    changes["compare_at_price_minor"] = money.compare_at_price_minor
    return changes


# --- records -------------------------------------------------------------------------


def group_choices(choices: Sequence[VariantChoice]) -> dict[str, list[VariantChoice]]:
    grouped: dict[str, list[VariantChoice]] = {}
    for choice in choices:
        grouped.setdefault(choice.variant_id, []).append(choice)
    return grouped


def option_records(
    options: Sequence[OptionRow], values: Sequence[OptionValueRow]
) -> tuple[OptionRecord, ...]:
    return tuple(
        OptionRecord(
            id=option.id,
            name=option.name,
            position=option.position,
            values=tuple(
                OptionValueRecord(v.id, v.value, v.position)
                for v in values
                if v.option_id == option.id
            ),
        )
        for option in options
    )


def variant_records(
    variants: Sequence[VariantRow], choices: Sequence[VariantChoice]
) -> tuple[VariantRecord, ...]:
    grouped = group_choices(choices)
    return tuple(
        VariantRecord(
            id=variant.id,
            sku=variant.sku,
            price_minor=variant.price_minor,
            compare_at_price_minor=variant.compare_at_price_minor,
            weight_grams=variant.weight_grams,
            stock=variant.stock,
            position=variant.position,
            option_values=tuple(
                VariantChoiceRecord(c.option_id, c.option_value_id)
                for c in sorted(grouped.get(variant.id, []), key=lambda c: c.option_id)
            ),
        )
        for variant in variants
    )


def image_record(image: ImageRow) -> ImageRecord:
    return ImageRecord(image.id, image.storage_key, image.alt_text, image.position)
