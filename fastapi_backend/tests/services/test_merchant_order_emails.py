"""The shipped notice on fulfilment (KAN-81): recorded in the fulfil transaction, then published.

The SQL is replaced here; ``tests/api/test_order_emails_e2e.py`` runs it on Postgres.
"""

import logging
from typing import Any

import pytest

from app.services import merchant_orders, order_email_job
from app.services.merchant_orders import StoreOrderEmails, StoreOrdersService
from app.services.order_email_job import OrderEmailJob
from app.services.order_email_templates import OrderEmailKind
from app.services.store_orders import InvalidOrderTransition, OrderStatus
from tests.fakes_email import RecordingEnqueuer

STORE_ID = "abcdefgh12345678abcdefgh"
SHIPPED = OrderEmailJob(STORE_ID, "order1", OrderEmailKind.ORDER_SHIPPED)


class TxSession:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")


def service(
    monkeypatch: pytest.MonkeyPatch,
    session: TxSession,
    *,
    emails: StoreOrderEmails | None,
    added: list[OrderEmailKind],
    fulfil_error: Exception | None = None,
) -> StoreOrdersService:
    async def fulfil(*args: Any) -> None:
        session.events.append("fulfil")
        if fulfil_error is not None:
            raise fulfil_error

    async def record(_session: Any, **kw: Any) -> list[OrderEmailKind]:
        session.events.append(f"record {kw['kinds'][0].value}")
        return added

    async def get(order_id: str) -> str:
        return order_id

    monkeypatch.setattr(merchant_orders, "fulfil_order", fulfil)
    monkeypatch.setattr(merchant_orders, "record_order_emails", record)
    built = StoreOrdersService(None, session, emails)  # type: ignore[arg-type]
    monkeypatch.setattr(built, "get", get)
    return built


async def test_fulfil_records_the_notice_before_the_commit_and_publishes_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = TxSession()
    enqueuer = RecordingEnqueuer()
    built = service(
        monkeypatch,
        session,
        emails=StoreOrderEmails(STORE_ID, enqueuer),
        added=[OrderEmailKind.ORDER_SHIPPED],
    )

    await built.fulfil("order1", "TRK1", None)

    assert session.events == ["fulfil", "record order_shipped", "commit"]
    assert enqueuer.jobs == [SHIPPED]


async def test_a_notice_that_was_not_recorded_is_not_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueuer = RecordingEnqueuer()
    built = service(
        monkeypatch,
        TxSession(),
        emails=StoreOrderEmails(STORE_ID, enqueuer),
        added=[],  # a store before 0012: the savepoint was rolled back
    )

    await built.fulfil("order1", "TRK1", None)

    assert enqueuer.jobs == []


async def test_a_publish_failure_still_fulfils_and_is_reported(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    reported: list[BaseException] = []
    monkeypatch.setattr(order_email_job, "report_exception", reported.append)
    session = TxSession()
    built = service(
        monkeypatch,
        session,
        emails=StoreOrderEmails(STORE_ID, RecordingEnqueuer(fail=True)),
        added=[OrderEmailKind.ORDER_SHIPPED],
    )

    assert await built.fulfil("order1", "TRK1", "DHL") == "order1"  # type: ignore[comparison-overlap]

    assert session.events[-1] == "commit"
    assert [str(error) for error in reported] == ["order_shipped: EnqueueFailed"]


async def test_a_refused_fulfilment_records_and_publishes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = TxSession()
    enqueuer = RecordingEnqueuer()
    built = service(
        monkeypatch,
        session,
        emails=StoreOrderEmails(STORE_ID, enqueuer),
        added=[OrderEmailKind.ORDER_SHIPPED],
        fulfil_error=InvalidOrderTransition(
            OrderStatus.FULFILLED, OrderStatus.FULFILLED
        ),
    )

    with pytest.raises(InvalidOrderTransition):
        await built.fulfil("order1", "TRK1", None)

    assert session.events == ["fulfil", "rollback"]
    assert enqueuer.jobs == []


async def test_without_emails_fulfilment_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = TxSession()
    built = service(monkeypatch, session, emails=None, added=[])

    await built.fulfil("order1", "TRK1", None)

    assert session.events == ["fulfil", "commit"]
