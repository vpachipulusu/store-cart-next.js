"""Subscription plan catalogue (KAN-42, E4.1).

Static, typed configuration for the three organisation plans. Billing endpoints
(KAN-43) and the Stripe webhook (KAN-44) read limits from here; nothing in this
module talks to Stripe or the database.

The limit values are configurable defaults: no planning document fixes them, so
change them here (one place) when the product owner decides. ``None`` means
unlimited. ``platform_fee_bps`` is reserved for a future per-order platform fee
(plan decision D9) and is 0 on every plan today.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class PlanKey(StrEnum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass(frozen=True)
class Plan:
    key: PlanKey
    name: str
    max_stores: int | None
    max_products: int | None
    max_staff: int | None
    platform_fee_bps: int = 0

    def __post_init__(self) -> None:
        values = (
            self.max_stores,
            self.max_products,
            self.max_staff,
            self.platform_fee_bps,
        )
        if any(value is not None and value < 0 for value in values):
            raise ValueError(f"Plan {self.key} has a negative limit or fee")


PLANS: Mapping[PlanKey, Plan] = MappingProxyType(
    {
        PlanKey.FREE: Plan(
            PlanKey.FREE, "Free", max_stores=1, max_products=25, max_staff=1
        ),
        PlanKey.PRO: Plan(
            PlanKey.PRO, "Pro", max_stores=3, max_products=1000, max_staff=5
        ),
        PlanKey.ENTERPRISE: Plan(
            PlanKey.ENTERPRISE,
            "Enterprise",
            max_stores=None,
            max_products=None,
            max_staff=None,
        ),
    }
)


def get_plan(key: str) -> Plan:
    """Look a plan up by key; raise ValueError for an unknown key."""
    try:
        return PLANS[PlanKey(key)]
    except ValueError:
        raise ValueError(f"Unknown subscription plan: {key!r}") from None


def is_within_limit(current: int, limit: int | None) -> bool:
    """True if one more item can be added under ``limit`` (None is unlimited)."""
    return limit is None or current < limit
