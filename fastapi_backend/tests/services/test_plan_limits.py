"""Plan limit errors, messages and the staff check (KAN-84). No database."""

import pytest

from app.core.plans import PLANS, PlanKey
from app.services.plan_limits import (
    PlanLimitReached,
    StaffLimitReached,
    plan_for,
    product_limit_message,
    require_staff_capacity,
    store_limit_message,
)


def test_unknown_tier_counts_as_free() -> None:
    assert plan_for("platinum") is PLANS[PlanKey.FREE]


def test_staff_below_the_limit_passes() -> None:
    require_staff_capacity(0, "free")
    require_staff_capacity(4, "pro")


def test_staff_at_the_limit_is_refused_with_an_upgrade_message() -> None:
    with pytest.raises(StaffLimitReached) as caught:
        require_staff_capacity(1, "free")

    assert isinstance(caught.value, PlanLimitReached)
    assert (
        str(caught.value)
        == "The Free plan allows 1 team member. Upgrade your plan to add more."
    )


def test_pro_limit_is_five_and_enterprise_is_unlimited() -> None:
    with pytest.raises(StaffLimitReached):
        require_staff_capacity(5, "pro")
    require_staff_capacity(10_000, "enterprise")


def test_unknown_tier_gets_the_free_staff_limit() -> None:
    with pytest.raises(StaffLimitReached):
        require_staff_capacity(1, "platinum")


def test_product_message_names_plan_and_limit() -> None:
    message = product_limit_message(PLANS[PlanKey.PRO])

    assert (
        message
        == "The Pro plan allows 1000 products per store. Upgrade your plan to add more."
    )


def test_store_message_names_the_plan_and_pluralises() -> None:
    assert store_limit_message(PLANS[PlanKey.FREE]) == (
        "The Free plan allows 1 store. Upgrade your plan to add more."
    )
    assert store_limit_message(PLANS[PlanKey.PRO]) == (
        "The Pro plan allows 3 stores. Upgrade your plan to add more."
    )
