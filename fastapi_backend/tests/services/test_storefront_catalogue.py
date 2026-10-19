"""Public catalogue service (KAN-75) on an in-memory repository: published-only reads,
slug and paging validation, public fields only, image URLs."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

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
from app.services.storefront_catalogue import (
    InvalidStorefrontQuery,
    PublicImage,
    StorefrontCatalogueService,
    StorefrontNotFound,
    clean_public_slug,
)

NOW = datetime(2026, 10, 19, tzinfo=UTC)
BASE = "https://img.example.test"


def product(slug: str, status: str = "active", pid: str | None = None) -> ProductRow:
    return ProductRow(
        id=pid or f"p-{slug}",
        title=slug.title(),
        slug=slug,
        description="Soft",
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeCatalogue:
    def __init__(self) -> None:
        self.products: dict[str, ProductRow] = {}
        self.categories: list[CategoryRow] = []
        self.links: dict[str, list[str]] = {}
        self.images: dict[str, list[ImageRow]] = {}
        self.variants: dict[str, list[VariantRow]] = {}
        self.choices: dict[str, list[VariantChoice]] = {}
        self.options: dict[str, list[OptionRow]] = {}
        self.values: dict[str, list[OptionValueRow]] = {}
        self.list_calls: list[dict[str, Any]] = []
        self.slug_lookups: list[str] = []

    def _matching(
        self, status: str | None, category_id: str | None
    ) -> list[ProductRow]:
        return [
            p
            for p in self.products.values()
            if (status is None or p.status == status)
            and (category_id is None or category_id in self.links.get(p.id, []))
        ]

    async def count_products(
        self,
        *,
        status: str | None,
        category_id: str | None,
        query: str | None = None,
        match_sku: bool = True,
    ) -> int:
        return len(self._matching(status, category_id))

    async def list_products(
        self,
        *,
        status: str | None,
        category_id: str | None,
        limit: int,
        offset: int,
        query: str | None = None,
        match_sku: bool = True,
    ) -> list[ProductSummaryRow]:
        self.list_calls.append(
            {
                "status": status,
                "category_id": category_id,
                "query": query,
                "match_sku": match_sku,
            }
        )
        return [
            ProductSummaryRow(
                id=p.id,
                title=p.title,
                slug=p.slug,
                status=p.status,
                created_at=p.created_at,
                updated_at=p.updated_at,
                variant_count=1,
                min_price_minor=1000,
                max_price_minor=1500,
            )
            for p in self._matching(status, category_id)[offset : offset + limit]
        ]

    async def get_product_by_slug(self, slug: str) -> ProductRow | None:
        self.slug_lookups.append(slug)
        return next((p for p in self.products.values() if p.slug == slug), None)

    async def get_category_by_slug(self, slug: str) -> CategoryRow | None:
        self.slug_lookups.append(slug)
        return next((c for c in self.categories if c.slug == slug), None)

    async def first_images(self, product_ids: Sequence[str]) -> dict[str, ImageRow]:
        return {pid: self.images[pid][0] for pid in product_ids if self.images.get(pid)}

    async def list_options(self, product_id: str) -> list[OptionRow]:
        return self.options.get(product_id, [])

    async def list_option_values(self, product_id: str) -> list[OptionValueRow]:
        return self.values.get(product_id, [])

    async def list_variants(self, product_id: str) -> list[VariantRow]:
        return self.variants.get(product_id, [])

    async def list_variant_choices(self, product_id: str) -> list[VariantChoice]:
        return self.choices.get(product_id, [])

    async def list_images(self, product_id: str) -> list[ImageRow]:
        return self.images.get(product_id, [])

    async def categories_of_product(self, product_id: str) -> list[CategoryParentRow]:
        slugs = {c.id: c.slug for c in self.categories}
        return [
            CategoryParentRow(
                c.name, c.slug, slugs.get(c.parent_id) if c.parent_id else None
            )
            for c in self.categories
            if c.id in self.links.get(product_id, [])
        ]

    async def list_categories(self, limit: int) -> list[CategoryRow]:
        return self.categories[:limit]


def image(key: str, alt: str | None = "A tee") -> ImageRow:
    return ImageRow(
        id=f"i-{key}", storage_key=f"stores/s1/{key}.jpg", alt_text=alt, position=0
    )


def variant(vid: str, stock: int = 3) -> VariantRow:
    return VariantRow(
        id=vid,
        sku=f"SKU-{vid}",
        price_minor=1200,
        compare_at_price_minor=1500,
        weight_grams=250,
        stock=stock,
        position=0,
    )


@pytest.fixture
def repo() -> FakeCatalogue:
    fake = FakeCatalogue()
    fake.products = {
        "p-tee": product("tee"),
        "p-draft": product("draft-hat", status="draft", pid="p-draft"),
    }
    fake.categories = [
        CategoryRow(
            id="c-1", name="Clothing", slug="clothing", parent_id=None, position=0
        ),
        CategoryRow(id="c-2", name="Tops", slug="tops", parent_id="c-1", position=0),
    ]
    return fake


async def test_listing_asks_only_for_published_products(repo: FakeCatalogue) -> None:
    service = StorefrontCatalogueService(repo, BASE, "GBP")

    page = await service.list_products()

    assert [item.slug for item in page.items] == ["tee"]
    assert page.total == 1
    assert page.currency == "GBP"
    assert repo.list_calls[0]["status"] == "active"


async def test_search_never_matches_skus(repo: FakeCatalogue) -> None:
    service = StorefrontCatalogueService(repo, BASE, "GBP")

    await service.list_products(query="SKU-1")

    assert repo.list_calls[0]["match_sku"] is False


async def test_listing_gives_the_first_image_as_a_public_url(
    repo: FakeCatalogue,
) -> None:
    repo.images["p-tee"] = [image("front")]
    service = StorefrontCatalogueService(repo, BASE + "/", "GBP")

    page = await service.list_products()

    assert page.items[0].image == PublicImage(f"{BASE}/stores/s1/front.jpg", "A tee")


async def test_without_a_public_image_origin_there_are_no_image_urls(
    repo: FakeCatalogue,
) -> None:
    repo.images["p-tee"] = [image("front")]
    service = StorefrontCatalogueService(repo, None, "GBP")

    listed = await service.list_products()
    read = await service.get_product("tee")

    assert listed.items[0].image is None
    assert read.images == ()


async def test_a_category_slug_filters_by_its_id(repo: FakeCatalogue) -> None:
    repo.links["p-tee"] = ["c-2"]
    service = StorefrontCatalogueService(repo, BASE, "GBP")

    page = await service.list_products(category_slug="Tops")

    assert [item.slug for item in page.items] == ["tee"]
    assert repo.list_calls[0]["category_id"] == "c-2"


@pytest.mark.parametrize("slug", ["missing", "Bad Slug!", "a--b", "x" * 201, " "])
async def test_an_unknown_or_malformed_category_is_not_found(
    repo: FakeCatalogue, slug: str
) -> None:
    service = StorefrontCatalogueService(repo, BASE, "GBP")

    with pytest.raises(StorefrontNotFound, match="Category not found"):
        await service.list_products(category_slug=slug)


@pytest.mark.parametrize(
    ("limit", "offset"), [(0, 0), (101, 0), (10, -1), (10, 10_001)]
)
async def test_paging_out_of_range_is_rejected(
    repo: FakeCatalogue, limit: int, offset: int
) -> None:
    service = StorefrontCatalogueService(repo, BASE, "GBP")

    with pytest.raises(InvalidStorefrontQuery):
        await service.list_products(limit=limit, offset=offset)


async def test_search_text_is_trimmed_and_blank_means_no_search(
    repo: FakeCatalogue,
) -> None:
    service = StorefrontCatalogueService(repo, BASE, "GBP")

    await service.list_products(query="  tee ")
    await service.list_products(query="   ")

    assert [call["query"] for call in repo.list_calls] == ["tee", None]


@pytest.mark.parametrize("query", ["x" * 101, "a\x00b"])
async def test_search_text_that_is_too_long_or_has_nul_is_rejected(
    repo: FakeCatalogue, query: str
) -> None:
    service = StorefrontCatalogueService(repo, BASE, "GBP")

    with pytest.raises(InvalidStorefrontQuery):
        await service.list_products(query=query)


async def test_a_draft_product_reads_like_an_unknown_one(repo: FakeCatalogue) -> None:
    service = StorefrontCatalogueService(repo, BASE, "GBP")

    with pytest.raises(StorefrontNotFound) as draft:
        await service.get_product("draft-hat")
    with pytest.raises(StorefrontNotFound) as missing:
        await service.get_product("no-such")

    assert str(draft.value) == str(missing.value) == "Product not found"


async def test_a_malformed_product_slug_never_reaches_the_database(
    repo: FakeCatalogue,
) -> None:
    service = StorefrontCatalogueService(repo, BASE, "GBP")

    with pytest.raises(StorefrontNotFound):
        await service.get_product("../etc")

    assert repo.slug_lookups == []


async def test_a_product_exposes_stock_as_a_flag_and_its_options(
    repo: FakeCatalogue,
) -> None:
    repo.options["p-tee"] = [OptionRow(id="o-size", name="Size", position=0)]
    repo.values["p-tee"] = [
        OptionValueRow(id="v-s", option_id="o-size", value="S", position=0),
        OptionValueRow(id="v-m", option_id="o-size", value="M", position=1),
    ]
    repo.variants["p-tee"] = [
        variant("var-s", stock=0),
        replace(variant("var-m"), position=1),
    ]
    repo.choices["p-tee"] = [
        VariantChoice(variant_id="var-s", option_id="o-size", option_value_id="v-s"),
        VariantChoice(variant_id="var-m", option_id="o-size", option_value_id="v-m"),
    ]
    repo.images["p-tee"] = [image("front"), image("back", alt=None)]
    repo.links["p-tee"] = ["c-2"]
    service = StorefrontCatalogueService(repo, BASE, "GBP")

    read = await service.get_product("TEE")

    assert [(v.id, v.in_stock, v.option_value_ids) for v in read.variants] == [
        ("var-s", False, ("v-s",)),
        ("var-m", True, ("v-m",)),
    ]
    assert [o.name for o in read.options] == ["Size"]
    assert [v.value for v in read.options[0].values] == ["S", "M"]
    assert [i.alt_text for i in read.images] == ["A tee", None]
    assert read.currency == "GBP"
    assert [(c.slug, c.parent_slug) for c in read.categories] == [("tops", "clothing")]
    assert not hasattr(read.variants[0], "sku")
    assert not hasattr(read.variants[0], "stock")


async def test_categories_name_their_parent_by_slug(repo: FakeCatalogue) -> None:
    service = StorefrontCatalogueService(repo, BASE, "GBP")

    categories = await service.list_categories()

    assert [(c.slug, c.parent_slug) for c in categories] == [
        ("clothing", None),
        ("tops", "clothing"),
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Tee", "tee"), (" tee-shirt ", "tee-shirt"), ("tee_shirt", None), ("", None)],
)
def test_clean_public_slug(raw: str, expected: str | None) -> None:
    assert clean_public_slug(raw) == expected
