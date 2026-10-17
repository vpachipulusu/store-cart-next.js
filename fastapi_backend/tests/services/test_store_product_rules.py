"""Product rules and error translation without a database (KAN-245).

The database-backed behaviour is in ``tests/api/test_products_e2e.py``; this module pins the
pure rules and the paths a real database cannot reach on demand (unknown constraint,
rollback on an unexpected error).
"""

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import DataError, IntegrityError

from app.core.plans import PLANS, Plan, PlanKey
from app.repositories.store_catalogue import VariantRow
from app.services.store_product_rules import (
    clean_money,
    clean_optional_text,
    clean_slug,
    clean_status,
    clean_text,
    image_key_for_store,
    slugify,
    translate_error,
    variant_changes,
)
from app.services.store_product_types import (
    CatalogueConflict,
    InvalidProduct,
    VariantPatch,
)
from app.services.store_products import StoreProductsService


def integrity(constraint: str | None, cause: bool = False) -> IntegrityError:
    driver = SimpleNamespace(constraint_name=constraint)
    orig: Any = SimpleNamespace(__cause__=driver) if cause else driver
    return IntegrityError("stmt", {}, orig)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Blue Tee", "blue-tee"),
        ("  Crème Brûlée!! ", "creme-brulee"),
        ("a" * 300, "a" * 200),
        ("---", ""),
        ("日本語", ""),
    ],
)
def test_slugify(title: str, expected: str) -> None:
    assert slugify(title) == expected


@pytest.mark.parametrize("slug", ["a", "a-b", "a1-b2-c3"])
def test_valid_slugs_pass(slug: str) -> None:
    assert clean_slug(slug) == slug


@pytest.mark.parametrize("slug", ["", "-a", "a-", "a--b", "A", "a b", "a_b", 5, None])
def test_invalid_slugs_fail(slug: object) -> None:
    with pytest.raises(InvalidProduct):
        clean_slug(slug)


def test_text_is_trimmed_and_bounded() -> None:
    assert clean_text("  hi  ", "Title", 5) == "hi"
    for bad in ("", "   ", "abcdef", "a\x07b", 3):
        with pytest.raises(InvalidProduct):
            clean_text(bad, "Title", 5)


def test_optional_text_allows_none_and_newlines_but_not_nul() -> None:
    assert clean_optional_text(None, "D", 10) is None
    assert clean_optional_text("a\nb", "D", 10) == "a\nb"
    for bad in ("a\x00", "x" * 11, 1):
        with pytest.raises(InvalidProduct):
            clean_optional_text(bad, "D", 10)


def test_status_accepts_only_draft_and_active() -> None:
    assert clean_status("active") == "active"
    for bad in ("archived", None, 1):
        with pytest.raises(InvalidProduct):
            clean_status(bad)


def test_money_rules() -> None:
    assert clean_money(100, None).compare_at_price_minor is None
    assert clean_money(100, 100).compare_at_price_minor is None
    assert clean_money(100, 150).compare_at_price_minor == 150
    for price, compare_at in (
        (-1, None),
        (1.5, None),
        (True, None),
        (100, 99),
        (100, "x"),
    ):
        with pytest.raises(InvalidProduct):
            clean_money(price, compare_at)


STORE = "store1"


@pytest.mark.parametrize("ext", ["jpg", "png", "webp"])
def test_image_key_of_the_store_prefix_passes(ext: str) -> None:
    key = f"stores/{STORE}/abc_DEF-1.{ext}"

    assert image_key_for_store(STORE, key) == key


@pytest.mark.parametrize(
    "key",
    [
        "stores/other/abc.png",
        f"stores/{STORE}x/abc.png",
        f"stores/{STORE}/a/b.png",
        f"stores/{STORE}/../other/abc.png",
        f"stores/{STORE}/abc.gif",
        f"stores/{STORE}/abc.png\n",
        f"stores/{STORE}/" + "a" * 300 + ".png",
        "",
        None,
        5,
    ],
)
def test_image_key_outside_the_prefix_fails(key: object) -> None:
    with pytest.raises(InvalidProduct):
        image_key_for_store(STORE, key)


def test_variant_changes_merge_with_the_stored_price() -> None:
    current = VariantRow("v", "SKU", 500, 900, None, 1, 0)

    assert variant_changes(current, VariantPatch(stock=3)) == {"stock": 3}
    assert variant_changes(current, VariantPatch(price_minor=900)) == {
        "price_minor": 900,
        "compare_at_price_minor": None,
    }
    with pytest.raises(InvalidProduct):
        variant_changes(current, VariantPatch(price_minor=1000))


def test_known_constraints_become_curated_conflicts() -> None:
    for name in (
        "uq_products_slug",
        "uq_variants_sku_lower",
        "uq_product_images_storage_key",
    ):
        error = translate_error(integrity(name))

        assert isinstance(error, CatalogueConflict)
        assert "constraint" not in str(error).lower()


def test_the_constraint_name_is_found_on_the_driver_cause() -> None:
    error = translate_error(integrity("uq_products_slug", cause=True))

    assert isinstance(error, CatalogueConflict)


def test_check_and_foreign_key_violations_are_invalid_input() -> None:
    assert isinstance(
        translate_error(integrity("ck_variants_price_minor")), InvalidProduct
    )
    assert isinstance(translate_error(integrity("fk_variants_product")), InvalidProduct)
    assert isinstance(
        translate_error(DataError("stmt", {}, Exception("integer out of range"))),
        InvalidProduct,
    )


def test_an_unknown_violation_is_not_translated() -> None:
    assert translate_error(integrity("something_else")) is None
    assert translate_error(integrity(None)) is None


class RecordingSession:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")


async def _unlimited() -> Plan:
    return PLANS[PlanKey.ENTERPRISE]


def service(session: RecordingSession) -> StoreProductsService:
    return StoreProductsService(object(), session, STORE, _unlimited)  # type: ignore[arg-type]


async def test_an_untranslatable_database_error_rolls_back_and_propagates() -> None:
    session = RecordingSession()

    async def write() -> None:
        raise integrity("something_else")

    with pytest.raises(IntegrityError):
        await service(session)._commit(write)

    assert session.events == ["rollback"]


async def test_a_curated_error_rolls_back_and_hides_the_driver_error() -> None:
    session = RecordingSession()

    async def write() -> None:
        raise integrity("uq_variants_sku_lower")

    with pytest.raises(CatalogueConflict) as caught:
        await service(session)._commit(write)

    assert caught.value.__cause__ is None
    assert session.events == ["rollback"]


async def test_any_other_failure_rolls_back_and_propagates() -> None:
    session = RecordingSession()

    async def write() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await service(session)._commit(write)

    assert session.events == ["rollback"]


async def test_a_deferred_violation_at_commit_is_translated() -> None:
    class FailsAtCommit(RecordingSession):
        async def commit(self) -> None:
            raise integrity("uq_product_images_product_position")

    session = FailsAtCommit()

    async def write() -> None:
        return None

    with pytest.raises(CatalogueConflict):
        await service(session)._commit(write)

    assert session.events == ["rollback"]


async def test_a_deadlock_is_a_curated_conflict() -> None:
    from sqlalchemy.exc import OperationalError

    session = RecordingSession()

    async def write() -> None:
        raise OperationalError("stmt", {}, SimpleNamespace(sqlstate="40P01"))

    with pytest.raises(CatalogueConflict):
        await service(session)._commit(write)

    assert session.events == ["rollback"]


async def test_another_database_failure_is_not_hidden() -> None:
    from sqlalchemy.exc import OperationalError

    session = RecordingSession()

    async def write() -> None:
        raise OperationalError("stmt", {}, SimpleNamespace(sqlstate="08006"))

    with pytest.raises(OperationalError):
        await service(session)._commit(write)

    assert session.events == ["rollback"]


def test_the_repository_refuses_unknown_update_columns() -> None:
    import asyncio

    from app.repositories.store_catalogue import StoreCatalogueRepository

    repository = StoreCatalogueRepository(object())  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        asyncio.run(repository.update_product("p", {"id; DROP TABLE products": 1}))
    with pytest.raises(ValueError):
        asyncio.run(repository.update_variant("v", "p", {"product_id": "x"}))
