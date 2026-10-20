"""``checkout.session.expired`` handling and the expiry sweep without a database (KAN-256).

The SQL itself runs against Postgres in ``tests/api/test_checkout_hardening_e2e.py``; these
tests cover the routing, the unusable inputs and the sweep's bounds.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import pytest

from app.repositories.connect_events import ConnectRoute
from app.services.store_checkout_expiry import (
    SESSION_LIFETIME,
    SWEEP_BATCH,
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


async def test_the_sweep_counts_what_it_cancelled_and_bounds_the_work() -> None:
    session = FakeStoreSession([("o1",), ("o2",)])

    cancelled = await sweep_expired_checkout_orders(session)  # type: ignore[arg-type]

    assert cancelled == 2
    _sql, params = session.statements[0]
    assert params == {"grace": SWEEP_GRACE.total_seconds(), "batch": SWEEP_BATCH}


async def test_the_sweep_accepts_its_own_grace_and_batch() -> None:
    session = FakeStoreSession([])

    await sweep_expired_checkout_orders(  # type: ignore[arg-type]
        session, grace=timedelta(minutes=1), batch=5
    )

    assert session.statements[0][1] == {"grace": 60.0, "batch": 5}
