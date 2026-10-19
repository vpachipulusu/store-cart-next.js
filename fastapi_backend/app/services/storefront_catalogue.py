"""Public catalogue reads of one store (KAN-75). No FastAPI imports.

Shoppers see published products only: every read filters ``status = 'active'`` (an
allowlist, so a status added later stays hidden), and a draft reads exactly like an unknown
slug. The records carry only what a storefront shows: no SKU, weight, exact stock or
timestamps. Image keys become public URLs under ``R2_PUBLIC_BASE_URL``; without it a product
simply has no image URLs. Reads only, so the service never commits.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.repositories.store_catalogue import (
    CategoryParentRow,
    CategoryRow,
    ImageRow,
    OptionRow,
    OptionValueRow,
    ProductRow,
    ProductSummaryRow,
    VariantChoice,
    VariantRow,
)
from app.services.store_product_rules import option_records
from app.services.store_product_types import (
    DEFAULT_PAGE_SIZE,
    MAX_CATEGORY_LIST,
    MAX_PAGE_SIZE,
    MAX_SEARCH_LENGTH,
    MAX_SLUG_LENGTH,
    CatalogueError,
    OptionRecord,
)

PUBLISHED = "active"
# Public listings stop deeper than any shopper pages: a deep OFFSET is a cheap way to load the database.
MAX_PUBLIC_OFFSET = 10_000


class CatalogueReader(Protocol):
    """The read side of ``StoreCatalogueRepository`` this service uses."""

    async def count_products(
        self,
        *,
        status: str | None,
        category_id: str | None,
        query: str | None = None,
        match_sku: bool = True,
    ) -> int: ...

    async def list_products(
        self,
        *,
        status: str | None,
        category_id: str | None,
        limit: int,
        offset: int,
        query: str | None = None,
        match_sku: bool = True,
    ) -> list[ProductSummaryRow]: ...

    async def get_product_by_slug(self, slug: str) -> ProductRow | None: ...

    async def get_category_by_slug(self, slug: str) -> CategoryRow | None: ...

    async def first_images(self, product_ids: Sequence[str]) -> dict[str, ImageRow]: ...

    async def list_options(self, product_id: str) -> list[OptionRow]: ...

    async def list_option_values(self, product_id: str) -> list[OptionValueRow]: ...

    async def list_variants(self, product_id: str) -> list[VariantRow]: ...

    async def list_variant_choices(self, product_id: str) -> list[VariantChoice]: ...

    async def list_images(self, product_id: str) -> list[ImageRow]: ...

    async def categories_of_product(
        self, product_id: str
    ) -> list[CategoryParentRow]: ...

    async def list_categories(self, limit: int) -> list[CategoryRow]: ...


_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class StorefrontNotFound(CatalogueError):
    """No published product or no category with this slug (404)."""


class InvalidStorefrontQuery(CatalogueError):
    """Paging or search input out of range (422)."""


@dataclass(frozen=True)
class PublicImage:
    url: str
    alt_text: str | None


@dataclass(frozen=True)
class PublicProductSummary:
    title: str
    slug: str
    min_price_minor: int | None
    max_price_minor: int | None
    image: PublicImage | None


@dataclass(frozen=True)
class PublicProductPage:
    items: tuple[PublicProductSummary, ...]
    currency: str
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class PublicVariant:
    id: str
    price_minor: int
    compare_at_price_minor: int | None
    in_stock: bool
    option_value_ids: tuple[str, ...]


@dataclass(frozen=True)
class PublicCategory:
    name: str
    slug: str
    parent_slug: str | None


@dataclass(frozen=True)
class PublicProduct:
    title: str
    slug: str
    description: str | None
    currency: str
    options: tuple[OptionRecord, ...]
    variants: tuple[PublicVariant, ...]
    images: tuple[PublicImage, ...]
    categories: tuple[PublicCategory, ...]


def clean_public_slug(value: str) -> str | None:
    """The lower-case slug, or None when it cannot name anything (no database read)."""
    slug = value.strip().lower()
    if not slug or len(slug) > MAX_SLUG_LENGTH or not _SLUG.match(slug):
        return None
    return slug


def _clean_query(query: str | None) -> str | None:
    if query is None:
        return None
    cleaned = query.strip()
    if len(cleaned) > MAX_SEARCH_LENGTH or "\x00" in cleaned:
        raise InvalidStorefrontQuery(
            f"Search text is at most {MAX_SEARCH_LENGTH} characters"
        )
    return cleaned or None


def _public_categories(rows: Sequence[CategoryRow]) -> tuple[PublicCategory, ...]:
    """Public view of ``rows``, parents named by slug."""
    slugs = {row.id: row.slug for row in rows}
    return tuple(
        PublicCategory(
            name=row.name,
            slug=row.slug,
            parent_slug=slugs.get(row.parent_id) if row.parent_id else None,
        )
        for row in rows
    )


def _option_value_ids(
    choices: Sequence[tuple[str, str, str]],
) -> dict[str, tuple[str, ...]]:
    """Each variant's option value ids, ordered by option id like the merchant API."""
    grouped: dict[str, list[tuple[str, str]]] = {}
    for variant_id, option_id, value_id in choices:
        grouped.setdefault(variant_id, []).append((option_id, value_id))
    return {
        variant_id: tuple(value_id for _, value_id in sorted(pairs))
        for variant_id, pairs in grouped.items()
    }


class StorefrontCatalogueService:
    def __init__(
        self, repository: CatalogueReader, image_base_url: str | None, currency: str
    ) -> None:
        self._repository = repository
        self._currency = currency
        self._image_base_url = image_base_url.rstrip("/") if image_base_url else None

    def _image(self, row: ImageRow) -> PublicImage | None:
        if self._image_base_url is None:
            return None
        return PublicImage(f"{self._image_base_url}/{row.storage_key}", row.alt_text)

    async def list_products(
        self,
        *,
        category_slug: str | None = None,
        query: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> PublicProductPage:
        """Published products, newest first. An unknown category is a 404, not an empty page."""
        if not 1 <= limit <= MAX_PAGE_SIZE or not 0 <= offset <= MAX_PUBLIC_OFFSET:
            raise InvalidStorefrontQuery("Page size or offset is out of range")
        search = _clean_query(query)
        category_id: str | None = None
        if category_slug is not None:
            slug = clean_public_slug(category_slug)
            category = (
                await self._repository.get_category_by_slug(slug) if slug else None
            )
            if category is None:
                raise StorefrontNotFound("Category not found")
            category_id = category.id
        total = await self._repository.count_products(
            status=PUBLISHED, category_id=category_id, query=search, match_sku=False
        )
        rows = await self._repository.list_products(
            status=PUBLISHED,
            category_id=category_id,
            query=search,
            limit=limit,
            offset=offset,
            match_sku=False,
        )
        images = await self._repository.first_images([row.id for row in rows])
        items = tuple(
            PublicProductSummary(
                title=row.title,
                slug=row.slug,
                min_price_minor=row.min_price_minor,
                max_price_minor=row.max_price_minor,
                image=self._image(images[row.id]) if row.id in images else None,
            )
            for row in rows
        )
        return PublicProductPage(items, self._currency, total, limit, offset)

    async def get_product(self, product_slug: str) -> PublicProduct:
        """A published product by slug; a draft is the same 404 as an unknown slug."""
        slug = clean_public_slug(product_slug)
        product = await self._repository.get_product_by_slug(slug) if slug else None
        if product is None or product.status != PUBLISHED:
            raise StorefrontNotFound("Product not found")
        options = await self._repository.list_options(product.id)
        values = await self._repository.list_option_values(product.id)
        variants = await self._repository.list_variants(product.id)
        choices = await self._repository.list_variant_choices(product.id)
        images = await self._repository.list_images(product.id)
        categories = await self._repository.categories_of_product(product.id)
        value_ids = _option_value_ids(
            [(c.variant_id, c.option_id, c.option_value_id) for c in choices]
        )
        return PublicProduct(
            title=product.title,
            slug=product.slug,
            description=product.description,
            currency=self._currency,
            options=option_records(options, values),
            variants=tuple(
                PublicVariant(
                    id=variant.id,
                    price_minor=variant.price_minor,
                    compare_at_price_minor=variant.compare_at_price_minor,
                    in_stock=variant.stock > 0,
                    option_value_ids=value_ids.get(variant.id, ()),
                )
                for variant in variants
            ),
            images=tuple(
                image for image in (self._image(row) for row in images) if image
            ),
            categories=tuple(
                PublicCategory(c.name, c.slug, c.parent_slug) for c in categories
            ),
        )

    async def list_categories(self) -> tuple[PublicCategory, ...]:
        """Every category, roots first then by parent and position (at most 1000)."""
        rows = await self._repository.list_categories(MAX_CATEGORY_LIST)
        return _public_categories(rows)
