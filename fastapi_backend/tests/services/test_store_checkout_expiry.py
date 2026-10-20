"""``checkout.session.expired`` handling and the expiry sweep without a database (KAN-256).

The SQL itself runs against Postgres in ``tests/api/test_checkout_hardening_e2e.py``; these
tests cover the routing, the unusable inputs and the sweep's bounds.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.stripe_billing import StripeError
from app.core.stripe_checkout import ExpireOutcome
from app.repositories.connect_events import ConnectRoute
from app.services.store_checkout_expiry import (
    ENDED_EVENT_TYPES,
    SESSION_LIFETIME,
    SWEEP_GRACE,
    cancel_expired_session_order,
    checkout_expired_handler,
    sweep_expired_checkout_orders,
)


class FakeResult:
    def __init__(self, rows: list[tuple[str]]) -> None:
        self._rows = rows

    def first(self) -> tuple[str] | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[tuple[str]]:
        return self._rows


class FakeStoreSession:
    def __init__(self, rows: list[tuple[str]]) -> None:
        self.rows = rows
        self.statements: list[tuple[str, dict[str, Any]]] = []
        self.commits = 0

    async def execute(self, statement: Any, params: dict[str, Any]) -> FakeResult:
        self.statements.append((str(statement), params))
        return FakeResult(self.rows)

    async def commit(self) -> None:
        self.commits += 1


def route(store_id: str | None) -> ConnectRoute:
    return ConnectRoute(organization_id="org1", account_id="acct_1", store_id=store_id)


def test_a_session_lives_longer_than_stripes_minimum_and_the_sweep_waits_longer() -> (
    None
):
    assert SESSION_LIFETIME > timedelta(minutes=30)
    assert SESSION_LIFETIME < timedelta(hours=24)
    assert SWEEP_GRACE > timedelta(0)


async def test_an_expired_session_cancels_the_order_linked_to_it() -> None:
    session = FakeStoreSession([("order1",)])

    cancelled = await cancel_expired_session_order(session, {"id": "cs_test_1"})  # type: ignore[arg-type]

    assert cancelled is True
    assert session.statements[0][1] == {"session_id": "cs_test_1"}
    assert "status = 'pending'" in session.statements[0][0]


async def test_an_expired_session_with_no_pending_order_changes_nothing() -> None:
    session = FakeStoreSession([])

    cancelled = await cancel_expired_session_order(session, {"id": "cs_test_1"})  # type: ignore[arg-type]

    assert cancelled is False


@pytest.mark.parametrize("bad", [None, 42, "", "x" * 300])
async def test_an_expired_event_without_a_usable_session_id_runs_no_query(
    bad: object,
) -> None:
    session = FakeStoreSession([("order1",)])

    cancelled = await cancel_expired_session_order(session, {"id": bad})  # type: ignore[arg-type]

    assert cancelled is False
    assert session.statements == []


async def test_the_handler_opens_the_routed_store_and_commits() -> None:
    session = FakeStoreSession([("order1",)])
    opened: list[str] = []

    @asynccontextmanager
    async def open_store(store_id: str) -> AsyncIterator[Any]:
        opened.append(store_id)
        yield session

    await checkout_expired_handler(open_store)(route("store1"), {"id": "cs_test_1"})

    assert opened == ["store1"]
    assert session.commits == 1


async def test_the_handler_ignores_an_event_routed_without_a_store() -> None:
    opened: list[str] = []

    @asynccontextmanager
    async def open_store(store_id: str) -> AsyncIterator[Any]:
        opened.append(store_id)
        yield FakeStoreSession([])

    await checkout_expired_handler(open_store)(route(None), {"id": "cs_test_1"})

    assert opened == []


class SweepSession:
    """Candidates for the select, a result for each conditional cancel."""

    def __init__(self, candidates: list[dict[str, Any]], cancels: bool = True) -> None:
        self.candidates = candidates
        self.cancels = cancels
        self.events: list[str] = []
        self.params: dict[str, Any] = {}

    async def execute(self, statement: Any, params: dict[str, Any]) -> Any:
        if "SELECT id" in str(statement):
            self.params = params
            return SweepRows(self.candidates)
        self.events.append(f"cancel {params['id']}")
        return FakeResult([("x",)] if self.cancels else [])

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")


class SweepRows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> "SweepRows":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class SweepStripe:
    def __init__(self, outcome: ExpireOutcome = ExpireOutcome.EXPIRED) -> None:
        self.outcome = outcome
        self.error: StripeError | None = None
        self.expired: list[tuple[str, str]] = []
        self.log: list[str] | None = None

    async def expire_session(self, account_id: str, session_id: str) -> ExpireOutcome:
        self.expired.append((account_id, session_id))
        if self.log is not None:
            self.log.append(f"expire {session_id}")
        if self.error is not None:
            raise self.error
        return self.outcome

    async def create_payment_session(self, request: Any) -> Any:
        raise AssertionError("not used")


def candidate(order_id: str, session_id: str | None) -> dict[str, Any]:
    return {"id": order_id, "session_id": session_id, "expires_at": datetime.now(UTC)}


async def test_the_sweep_cancels_an_order_only_after_stripe_says_the_session_expired() -> (
    None
):
    session = SweepSession([candidate("o1", "cs_1")])
    stripe = SweepStripe()
    stripe.log = session.events

    page = await sweep_expired_checkout_orders(session, stripe, "acct_1")  # type: ignore[arg-type]

    assert (page.examined, page.cancelled) == (1, 1)
    assert session.events == ["rollback", "expire cs_1", "cancel o1", "commit"]
    assert stripe.expired == [("acct_1", "cs_1")]


async def test_a_session_the_shopper_completed_is_left_pending() -> None:
    session = SweepSession([candidate("o1", "cs_1")])

    page = await sweep_expired_checkout_orders(
        session,
        SweepStripe(ExpireOutcome.COMPLETE),  # type: ignore[arg-type]
        "acct_1",
    )

    assert (page.examined, page.cancelled) == (1, 0)
    assert "cancel o1" not in session.events


async def test_an_order_stripe_cannot_verify_is_left_pending() -> None:
    session = SweepSession([candidate("o1", "cs_1")])
    stripe = SweepStripe()
    stripe.error = StripeError("down")

    page = await sweep_expired_checkout_orders(session, stripe, "acct_1")  # type: ignore[arg-type]

    assert page.cancelled == 0
    assert "cancel o1" not in session.events


@pytest.mark.parametrize("no_stripe", ["no client", "no account"])
async def test_a_session_cannot_be_verified_without_stripe_or_an_account(
    no_stripe: str,
) -> None:
    session = SweepSession([candidate("o1", "cs_1")])
    stripe = None if no_stripe == "no client" else SweepStripe()
    account = "acct_1" if no_stripe == "no client" else None

    page = await sweep_expired_checkout_orders(session, stripe, account)  # type: ignore[arg-type]

    assert page.cancelled == 0


async def test_an_order_with_no_session_is_cancelled_without_a_stripe_call() -> None:
    session = SweepSession([candidate("o1", None)])
    stripe = SweepStripe()

    page = await sweep_expired_checkout_orders(session, stripe, None)  # type: ignore[arg-type]

    assert page.cancelled == 1
    assert stripe.expired == []


async def test_an_order_that_moved_meanwhile_is_not_counted() -> None:
    session = SweepSession([candidate("o1", None)], cancels=False)

    page = await sweep_expired_checkout_orders(session, None, None)

    assert (page.examined, page.cancelled) == (1, 0)


async def test_the_page_carries_a_cursor_and_the_next_page_starts_after_it() -> None:
    session = SweepSession([candidate("o1", None), candidate("o2", None)])

    page = await sweep_expired_checkout_orders(session, None, None, batch=2)
    assert page.cursor is not None
    assert page.cursor.order_id == "o2"
    await sweep_expired_checkout_orders(session, None, None, batch=2, after=page.cursor)

    assert session.params["after_id"] == "o2"
    assert session.params["batch"] == 2
    assert session.params["grace"] == SWEEP_GRACE.total_seconds()


async def test_an_empty_page_has_no_cursor() -> None:
    page = await sweep_expired_checkout_orders(SweepSession([]), None, None)  # type: ignore[arg-type]

    assert (page.examined, page.cancelled, page.cursor) == (0, 0, None)


def test_a_failed_async_payment_ends_the_order_like_an_expired_session() -> None:
    assert set(ENDED_EVENT_TYPES) == {
        "checkout.session.expired",
        "checkout.session.async_payment_failed",
    }


async def test_the_start_sweep_reads_only_orders_without_a_session() -> None:
    session = SweepSession([candidate("o1", None)])

    page = await sweep_expired_checkout_orders(
        session,  # type: ignore[arg-type]
        None,
        None,
        batch=5,
        with_sessions=False,
    )

    assert session.params["with_sessions"] is False
    assert page.cancelled == 1


async def test_a_sweep_that_verifies_reads_orders_with_sessions_too() -> None:
    session = SweepSession([])

    await sweep_expired_checkout_orders(session, None, None)  # type: ignore[arg-type]

    assert session.params["with_sessions"] is True


async def test_an_unverified_order_is_logged_with_its_id_and_the_error_class(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = SweepSession([candidate("o1", "cs_1")])
    stripe = SweepStripe()
    stripe.error = StripeError("secret detail")

    with caplog.at_level("WARNING"):
        await sweep_expired_checkout_orders(session, stripe, "acct_1")  # type: ignore[arg-type]

    record = next(r for r in caplog.records if "not verified" in r.getMessage())
    assert "StripeError" in record.getMessage()
    assert "secret detail" not in record.getMessage()
    assert record.order_id == "o1"  # type: ignore[attr-defined]
