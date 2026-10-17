"""Product plan limit in ``StoreProductsService.create`` without a database (KAN-84)."""

from typing import Any

import pytest

from app.core.plans import PLANS, Plan, PlanKey
from app.services.store_product_types import (
    NewProduct,
    NewVariant,
    ProductLimitReached,
)
from app.services.store_products import StoreProductsService


class Session:
    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class FakeRepository:
    """Records the order of the calls ``create`` makes; reads return fixed values."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.events: list[str] = []

    async def lock_catalogue(self) -> None:
        self.events.append("lock")

    async def count_all_products(self) -> int:
        self.events.append("count")
        return self.count

    def __getattr__(self, name: str) -> Any:
        async def record(*args: object, **kwargs: object) -> None:
            self.events.append(name)

        return record


def build(plan_key: PlanKey, count: int) -> tuple[StoreProductsService, FakeRepository]:
    repository = FakeRepository(count)

    async def plan() -> Plan:
        return PLANS[plan_key]

    service = StoreProductsService(repository, Session(), "store", plan)  # type: ignore[arg-type]

    async def get(product_id: str) -> str:
        return product_id

    service.get = get  # type: ignore[method-assign,assignment]
    return service, repository


NEW = NewProduct(title="Mug", variants=[NewVariant(sku="MUG-1", price_minor=500)])


async def test_pro_plan_allows_the_1000th_product() -> None:
    service, repository = build(PlanKey.PRO, 999)

    await service.create(NEW)

    assert "insert_product" in repository.events


async def test_pro_plan_refuses_the_1001st_product() -> None:
    service, repository = build(PlanKey.PRO, 1000)

    with pytest.raises(ProductLimitReached) as caught:
        await service.create(NEW)

    assert str(caught.value) == (
        "The Pro plan allows 1000 products per store. Upgrade your plan to add more."
    )
    assert "insert_product" not in repository.events


async def test_create_takes_the_lock_before_it_counts() -> None:
    service, repository = build(PlanKey.FREE, 0)

    await service.create(NEW)

    assert repository.events[:3] == ["lock", "count", "insert_product"]


async def test_unlimited_plan_neither_locks_nor_counts() -> None:
    service, repository = build(PlanKey.ENTERPRISE, 10**6)

    await service.create(NEW)

    assert "lock" not in repository.events
    assert "count" not in repository.events
