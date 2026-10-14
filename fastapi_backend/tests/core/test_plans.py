import dataclasses

import pytest

from app.core.plans import PLANS, Plan, PlanKey, get_plan, is_within_limit


def test_catalogue_has_exactly_free_pro_and_enterprise():
    assert set(PLANS) == {PlanKey.FREE, PlanKey.PRO, PlanKey.ENTERPRISE}
    assert [p.key for p in PLANS.values()] == list(PLANS)


@pytest.mark.parametrize(
    ("key", "stores", "products", "staff"),
    [
        (PlanKey.FREE, 1, 25, 1),
        (PlanKey.PRO, 3, 1000, 5),
        (PlanKey.ENTERPRISE, None, None, None),
    ],
)
def test_plan_limits(key, stores, products, staff):
    plan = get_plan(key)

    assert plan.max_stores == stores
    assert plan.max_products == products
    assert plan.max_staff == staff


@pytest.mark.parametrize("key", list(PlanKey))
def test_every_plan_has_zero_platform_fee(key):
    assert get_plan(key).platform_fee_bps == 0


def test_get_plan_accepts_string_keys():
    assert get_plan("pro") is PLANS[PlanKey.PRO]


@pytest.mark.parametrize("key", ["gold", "", "PRO", None])
def test_get_plan_rejects_unknown_keys(key):
    with pytest.raises(ValueError, match="Unknown subscription plan"):
        get_plan(key)


def test_plans_are_immutable():
    plan = get_plan(PlanKey.FREE)

    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.max_stores = 99  # type: ignore[misc]


def test_catalogue_is_read_only():
    with pytest.raises(TypeError):
        PLANS[PlanKey.FREE] = get_plan(PlanKey.PRO)  # type: ignore[index]


def test_limits_increase_from_free_to_pro():
    free, pro = get_plan(PlanKey.FREE), get_plan(PlanKey.PRO)

    assert free.max_stores is not None and pro.max_stores is not None
    assert free.max_stores < pro.max_stores
    assert free.max_products is not None and pro.max_products is not None
    assert free.max_products < pro.max_products
    assert free.max_staff is not None and pro.max_staff is not None
    assert free.max_staff < pro.max_staff


def test_plan_rejects_negative_limits_and_fee():
    with pytest.raises(ValueError):
        Plan(PlanKey.FREE, "Free", max_stores=-1, max_products=1, max_staff=1)
    with pytest.raises(ValueError):
        Plan(
            PlanKey.FREE,
            "Free",
            max_stores=1,
            max_products=1,
            max_staff=1,
            platform_fee_bps=-1,
        )


def test_is_within_limit():
    assert is_within_limit(0, 1)
    assert not is_within_limit(1, 1)
    assert is_within_limit(10**9, None)
