"""Search text cleaning, LIKE escaping and the category list bound (KAN-246). No database."""

from typing import Any, cast

import pytest

from app.repositories.store_catalogue import CategoryRow, search_pattern
from app.services.store_product_types import (
    MAX_CATEGORY_LIST,
    MAX_SEARCH_LENGTH,
    InvalidProduct,
)
from app.services.store_products import StoreProductsService, _clean_search


def test_search_pattern_is_none_without_a_query() -> None:
    assert search_pattern(None) is None


def test_search_pattern_escapes_the_escape_character_before_the_wildcards() -> None:
    assert search_pattern("a\\b%_") == "%a\\\\b\\%\\_%"
    assert search_pattern("\\%") == "%\\\\\\%%"


def test_clean_search_trims_and_maps_blank_to_none() -> None:
    assert _clean_search("  Mug ") == "Mug"
    assert _clean_search("   ") is None
    assert _clean_search(None) is None


def test_clean_search_accepts_100_characters_after_trimming() -> None:
    assert _clean_search(f" {'x' * MAX_SEARCH_LENGTH} ") == "x" * MAX_SEARCH_LENGTH


@pytest.mark.parametrize("bad", ["x" * (MAX_SEARCH_LENGTH + 1), "a\x00b"])
def test_clean_search_rejects_long_text_and_nul(bad: str) -> None:
    with pytest.raises(InvalidProduct):
        _clean_search(bad)


class FakeRepository:
    def __init__(self, count: int) -> None:
        self._rows = [
            CategoryRow(id=str(i), name="n", slug=f"s{i}", parent_id=None, position=i)
            for i in range(count)
        ]

    async def list_categories(self, limit: int) -> list[CategoryRow]:
        return self._rows[:limit]


def service_with(count: int) -> StoreProductsService:
    repository: Any = FakeRepository(count)
    return StoreProductsService(repository, cast(Any, None), "store", cast(Any, None))


async def test_category_list_is_truncated_above_the_cap() -> None:
    result = await service_with(MAX_CATEGORY_LIST + 1).list_categories()

    assert len(result.items) == MAX_CATEGORY_LIST
    assert result.truncated is True


async def test_category_list_at_the_cap_is_not_truncated() -> None:
    result = await service_with(MAX_CATEGORY_LIST).list_categories()

    assert len(result.items) == MAX_CATEGORY_LIST
    assert result.truncated is False


async def test_category_list_of_an_empty_store_is_empty() -> None:
    result = await service_with(0).list_categories()

    assert result.items == ()
    assert result.truncated is False
