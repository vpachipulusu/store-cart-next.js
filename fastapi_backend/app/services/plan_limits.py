"""Subscription plan limits on create (KAN-84): the errors, messages and staff check.

``app.core.plans`` holds the numbers; this module turns "one more would pass the limit"
into a curated error whose message tells the merchant to upgrade. The store limit lives in
``organizations.py`` (KAN-45) and the product limit in ``store_products.py``; the staff
helper below is called by the invitation flow when it lands (KAN-62), the only path that
adds members besides the owner row created with the organisation.

A limit of ``None`` is unlimited. Products are counted per store (each store has its own
database), staff per organisation (every membership, the owner included).
"""

from app.core.plans import PLANS, Plan, PlanKey, is_within_limit

UPGRADE_HINT = "Upgrade your plan to add more."


class PlanLimitReached(Exception):
    """The plan allows no more of this resource. The message is safe to show (409)."""


class StaffLimitReached(PlanLimitReached):
    """The organisation's plan allows no more staff members."""


def plan_for(tier: str) -> Plan:
    """The plan for a tier string; an unknown tier counts as free."""
    try:
        return PLANS[PlanKey(tier)]
    except ValueError:
        return PLANS[PlanKey.FREE]


def product_limit_message(plan: Plan) -> str:
    return (
        f"The {plan.name} plan allows {plan.max_products} products per store. "
        f"{UPGRADE_HINT}"
    )


def staff_limit_message(plan: Plan) -> str:
    return f"The {plan.name} plan allows {plan.max_staff} team members. {UPGRADE_HINT}"


def require_staff_capacity(current_members: int, tier: str) -> None:
    """Raise ``StaffLimitReached`` unless one more member fits under the plan.

    ``current_members`` is the organisation's membership count read in the same
    transaction as the insert, under the organisation row lock (as ``create_store`` does);
    the helper cannot check that, the caller must.
    """
    plan = plan_for(tier)
    if not is_within_limit(current_members, plan.max_staff):
        raise StaffLimitReached(staff_limit_message(plan))
