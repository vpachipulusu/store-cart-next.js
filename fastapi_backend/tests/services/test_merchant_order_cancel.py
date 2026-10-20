"""A merchant cancelling a pending order without a database (KAN-256).

The SQL runs against Postgres in ``tests/api/test_checkout_hardening_e2e.py``; these tests
cover every branch of the decision: when Stripe is asked, when the order is left alone and
which error says why.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.stripe_billing import StripeError
from app.core.stripe_checkout import ExpireOutcome
from app.services.merchant_order_cancel import (
    MerchantOrderCancelService,
    OrderCancelUnavailable,
    OrderNotCancellable,
    OrderPaymentInProgress,
)
from app.services.store_orders import OrderNotFound

ACCOUNT = "acct_merchant1"
FUTURE = datetime.now(UTC) + timedelta(minutes=20)
PAST = datetime.now(UTC) - timedelta(minutes=1)


class FakeResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def mappings(self) -> "FakeResult":
        return self

    def first(self) -> Any:
        return self._row


class FakeSession:
    """Answers the state read with ``state`` and the conditional cancel with ``cancels``."""

    def __init__(self, state: dict[str, Any] | None, *, cancels: bool = True) -> None:
        self.state = state
        self.cancels = cancels
        self.commits = 0
        self.rollbacks = 0
        self.fail_cancel = False

    async def execute(self, statement: Any, params: dict[str, Any]) -> FakeResult:
        if "SELECT status" in str(statement):
            return FakeResult(self.state)
        if self.fail_cancel:
            raise RuntimeError("database down")
        return FakeResult({"id": params["id"]} if self.cancels else None)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeStripe:
    def __init__(self) -> None:
        self.expired: list[tuple[str, str]] = []
        self.outcome = ExpireOutcome.EXPIRED
        self.error: StripeError | None = None

    async def expire_session(self, account_id: str, session_id: str) -> ExpireOutcome:
        self.expired.append((account_id, session_id))
        if self.error is not None:
            raise self.error
        return self.outcome

    async def create_payment_session(self, request: Any) -> Any:
        raise AssertionError("not used")


class FakeOrders:
    def __init__(self) -> None:
        self.read: list[str] = []

    async def get(self, order_id: str) -> str:
        self.read.append(order_id)
        return f"detail of {order_id}"


def state(
    *,
    status: str = "pending",
    session: str | None = "cs_1",
    expires_at: datetime | None = FUTURE,
) -> dict[str, Any]:
    return {
        "status": status,
        "stripe_checkout_session_id": session,
        "checkout_expires_at": expires_at,
    }


def service(
    session: FakeSession,
    stripe: FakeStripe,
    account_id: str | None = ACCOUNT,
) -> tuple[MerchantOrderCancelService, FakeOrders]:
    orders = FakeOrders()
    return (
        MerchantOrderCancelService(orders, session, stripe, account_id),  # type: ignore[arg-type]
        orders,
    )


async def test_the_session_is_expired_then_the_order_cancelled_and_returned() -> None:
    session, stripe = FakeSession(state()), FakeStripe()
    cancel, orders = service(session, stripe)

    detail = await cancel.cancel("o1")

    assert stripe.expired == [(ACCOUNT, "cs_1")]
    assert session.rollbacks == 1  # no transaction held across the Stripe call
    assert session.commits == 1
    assert detail == "detail of o1"
    assert orders.read == ["o1"]


async def test_an_unknown_order_is_not_found_and_stripe_is_not_asked() -> None:
    session, stripe = FakeSession(None), FakeStripe()
    cancel, _ = service(session, stripe)

    with pytest.raises(OrderNotFound):
        await cancel.cancel("nope")

    assert stripe.expired == []


@pytest.mark.parametrize("status", ["paid", "fulfilled", "cancelled", "refunded"])
async def test_only_a_pending_order_can_be_cancelled(status: str) -> None:
    session, stripe = FakeSession(state(status=status)), FakeStripe()
    cancel, _ = service(session, stripe)

    with pytest.raises(OrderNotCancellable):
        await cancel.cancel("o1")

    assert stripe.expired == []
    assert session.commits == 0


async def test_a_session_the_shopper_paid_blocks_the_cancel() -> None:
    session, stripe = FakeSession(state()), FakeStripe()
    stripe.outcome = ExpireOutcome.COMPLETE
    cancel, _ = service(session, stripe)

    with pytest.raises(OrderPaymentInProgress):
        await cancel.cancel("o1")

    assert session.commits == 0


async def test_a_stripe_failure_leaves_the_order_alone() -> None:
    session, stripe = FakeSession(state()), FakeStripe()
    stripe.error = StripeError("down")
    cancel, _ = service(session, stripe)

    with pytest.raises(OrderCancelUnavailable):
        await cancel.cancel("o1")

    assert session.commits == 0


async def test_a_session_without_a_connected_account_cannot_be_closed() -> None:
    session, stripe = FakeSession(state()), FakeStripe()
    cancel, _ = service(session, stripe, account_id=None)

    with pytest.raises(OrderCancelUnavailable):
        await cancel.cancel("o1")

    assert (stripe.expired, session.commits) == ([], 0)


async def test_an_unlinked_order_that_may_still_have_a_session_is_not_cancelled() -> (
    None
):
    session, stripe = FakeSession(state(session=None)), FakeStripe()
    cancel, _ = service(session, stripe)

    with pytest.raises(OrderCancelUnavailable):
        await cancel.cancel("o1")

    assert (stripe.expired, session.commits) == ([], 0)


@pytest.mark.parametrize("expires_at", [PAST, None])
async def test_an_unlinked_order_past_its_expiry_or_outside_checkout_is_cancelled(
    expires_at: datetime | None,
) -> None:
    session, stripe = (
        FakeSession(state(session=None, expires_at=expires_at)),
        FakeStripe(),
    )
    cancel, _ = service(session, stripe)

    await cancel.cancel("o1")

    assert stripe.expired == []
    assert session.commits == 1


async def test_an_order_that_moved_after_the_read_is_not_cancellable() -> None:
    session, stripe = FakeSession(state(), cancels=False), FakeStripe()
    cancel, orders = service(session, stripe)

    with pytest.raises(OrderNotCancellable):
        await cancel.cancel("o1")

    assert orders.read == []


async def test_a_database_failure_rolls_back_and_propagates() -> None:
    session, stripe = FakeSession(state()), FakeStripe()
    session.fail_cancel = True
    cancel, _ = service(session, stripe)

    with pytest.raises(RuntimeError):
        await cancel.cancel("o1")

    assert session.rollbacks == 2  # the read transaction, then the failed write
