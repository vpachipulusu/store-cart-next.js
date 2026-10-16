"""PlanPricesService (KAN-208): the four configured Stripe prices, tolerant of failures."""

from app.core.stripe_billing import StripeError, StripeNotFound
from app.services.plan_prices import PlanPrices, PlanPricesService, TierPrices

IDS = {
    ("pro", "monthly"): "price_pm",
    ("pro", "yearly"): "price_py",
    ("enterprise", "monthly"): "price_em",
    ("enterprise", "yearly"): "price_ey",
}


class FakePrices:
    def __init__(self, amounts: dict[str, int | None], fail: set[str] | None = None):
        self.amounts = amounts
        self.fail = fail or set()
        self.asked: list[str] = []

    async def get_unit_amount(self, price_id: str) -> int | None:
        self.asked.append(price_id)
        if price_id in self.fail:
            raise StripeNotFound("x")
        return self.amounts.get(price_id)


async def test_maps_each_configured_price_to_its_tier_and_interval() -> None:
    reader = FakePrices(
        {"price_pm": 1900, "price_py": 19000, "price_em": 9900, "price_ey": 99000}
    )

    result = await PlanPricesService(reader, IDS).prices()

    assert result == PlanPrices(
        pro=TierPrices(monthly=1900, yearly=19000),
        enterprise=TierPrices(monthly=9900, yearly=99000),
    )


async def test_unconfigured_ids_are_none_and_never_requested() -> None:
    reader = FakePrices({"price_pm": 1900})
    ids = {("pro", "monthly"): "price_pm"}

    result = await PlanPricesService(reader, ids).prices()

    assert result.pro == TierPrices(monthly=1900, yearly=None)
    assert result.enterprise == TierPrices(monthly=None, yearly=None)
    assert reader.asked == ["price_pm"]


async def test_a_failing_price_is_none_and_the_others_survive() -> None:
    reader = FakePrices({"price_pm": 1900, "price_py": 19000}, fail={"price_pm"})

    result = await PlanPricesService(reader, IDS).prices()

    assert result.pro == TierPrices(monthly=None, yearly=19000)


async def test_stripe_not_configured_gives_all_none() -> None:
    result = await PlanPricesService(None, IDS).prices()

    assert result == PlanPrices(TierPrices(None, None), TierPrices(None, None))


async def test_stripe_error_does_not_escape() -> None:
    class Broken:
        async def get_unit_amount(self, price_id: str) -> int | None:
            raise StripeError("down")

    result = await PlanPricesService(Broken(), IDS).prices()

    assert result.pro.monthly is None
