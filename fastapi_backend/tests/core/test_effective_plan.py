from datetime import UTC, datetime, timedelta

import pytest

from app.core.plans import PlanKey, effective_plan_key

NOW = datetime(2026, 6, 1, tzinfo=UTC)
LATER = NOW + timedelta(days=30)


@pytest.mark.parametrize(
    ("tier", "granted", "until", "expected"),
    [
        ("free", None, None, PlanKey.FREE),
        ("pro", None, None, PlanKey.PRO),
        ("free", "pro", LATER, PlanKey.PRO),
        ("free", "enterprise", LATER, PlanKey.ENTERPRISE),
        ("enterprise", "pro", LATER, PlanKey.ENTERPRISE),
        ("pro", "enterprise", LATER, PlanKey.ENTERPRISE),
        ("free", "pro", NOW, PlanKey.FREE),
        ("free", "pro", NOW - timedelta(days=1), PlanKey.FREE),
        ("pro", "enterprise", NOW - timedelta(seconds=1), PlanKey.PRO),
        ("legacy", None, None, PlanKey.FREE),
        ("free", "bogus", LATER, PlanKey.FREE),
        ("free", "pro", None, PlanKey.FREE),
    ],
)
def test_effective_plan_is_the_higher_of_stripe_plan_and_unexpired_grant(
    tier, granted, until, expected
):
    assert effective_plan_key(tier, granted, until, NOW) is expected
