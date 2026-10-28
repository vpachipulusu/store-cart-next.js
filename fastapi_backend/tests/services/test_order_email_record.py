"""The email writes in the order's store transaction (KAN-81): address check and error handling.

The SQL itself runs on Postgres in ``tests/services/test_store_order_emails_schema_e2e.py``; here
a session fails every statement with a chosen SQLSTATE, carrying the shopper's address in its
parameters the way a real driver error does.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.services import order_email_record
from app.services.order_email_job import PAID_KINDS, OrderEmailFailed
from app.services.order_email_record import (
    clean_customer_email,
    pending_jobs,
    record_order_emails,
)

STORE_ID = "abcdefgh12345678abcdefgh"
ORDER_ID = "order1"
CUSTOMER = "shopper@example.com"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Shopper@Example.com ", "Shopper@Example.com"),
        ("a@b", "a@b"),
        ("@example.com", None),
        ("@x@example.com", None),  # the CHECK looks at the first @
        ("no-at-sign", None),
        ("a b@example.com", None),
        ("a\n@example.com", None),
        ("x" * 250 + "@a.co", None),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_the_customer_email_is_trimmed_and_checked(
    raw: object, expected: str | None
) -> None:
    assert clean_customer_email(raw) == expected


class _Orig(Exception):
    def __init__(self, sqlstate: str | None) -> None:
        super().__init__(f"driver error for {CUSTOMER}")
        if sqlstate is not None:
            self.sqlstate = sqlstate


class FailingStoreSession:
    """A store session whose every statement fails with ``sqlstate``."""

    def __init__(self, sqlstate: str | None) -> None:
        self.sqlstate = sqlstate
        self.savepoints = 0

    def begin_nested(self) -> Any:
        @asynccontextmanager
        async def savepoint() -> AsyncIterator[None]:
            self.savepoints += 1
            yield

        return savepoint()

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise DBAPIError(
            "UPDATE orders SET customer_email = $1",
            {"email": CUSTOMER},
            _Orig(self.sqlstate),
        )


@pytest.fixture
def reported(monkeypatch: pytest.MonkeyPatch) -> list[BaseException]:
    events: list[BaseException] = []
    monkeypatch.setattr(order_email_record, "report_exception", events.append)
    return events


async def write(session: FailingStoreSession) -> list[Any]:
    return await record_order_emails(
        session,  # type: ignore[arg-type]
        store_id=STORE_ID,
        order_id=ORDER_ID,
        kinds=PAID_KINDS,
        customer_email=CUSTOMER,
    )


async def read(session: FailingStoreSession) -> list[Any]:
    return await pending_jobs(
        session,  # type: ignore[arg-type]
        store_id=STORE_ID,
        order_id=ORDER_ID,
        kinds=PAID_KINDS,
    )


def assert_no_address(caplog: pytest.LogCaptureFixture, *errors: BaseException) -> None:
    logged = caplog.text + " ".join(str(vars(r)) for r in caplog.records)
    assert CUSTOMER not in logged
    for error in errors:
        assert CUSTOMER not in str(error)
        assert error.__cause__ is None and error.__suppress_context__ in (True, False)


@pytest.mark.parametrize("sqlstate", ["42P01", "42703"])
async def test_a_store_before_0012_skips_quietly_in_local_and_test(
    sqlstate: str, caplog: pytest.LogCaptureFixture, reported: list[BaseException]
) -> None:
    caplog.set_level(logging.DEBUG)
    session = FailingStoreSession(sqlstate)

    assert (await write(session), await read(session)) == ([], [])

    assert session.savepoints == 2
    assert reported == []
    assert "order email skipped" in caplog.text
    assert_no_address(caplog)


async def test_a_store_before_0012_is_a_sentry_event_outside_local(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    reported: list[BaseException],
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "VERCEL_ENV", None)

    assert await write(FailingStoreSession("42P01")) == []

    assert [str(error) for error in reported] == [
        "store schema: DBAPIError sqlstate=42P01"
    ]
    assert_no_address(caplog, *reported)


@pytest.mark.parametrize(
    "sqlstate",
    [
        "40001",
        "40P01",
        "55P03",
        "57014",
        "08006",  # connection failure
        "08003",
        "53300",  # too many connections
        "53100",
        "57P01",  # admin shutdown
        "57P03",
    ],
)
async def test_a_transient_error_is_raised_wrapped_so_the_change_is_retried(
    sqlstate: str, caplog: pytest.LogCaptureFixture, reported: list[BaseException]
) -> None:
    caplog.set_level(logging.DEBUG)

    with pytest.raises(OrderEmailFailed) as on_write:
        await write(FailingStoreSession(sqlstate))
    with pytest.raises(OrderEmailFailed) as on_read:
        await read(FailingStoreSession(sqlstate))

    for raised in (on_write, on_read):
        assert str(raised.value).startswith("DBAPIError")
        assert raised.value.__suppress_context__  # the driver error does not ride along
    assert reported == []
    assert_no_address(caplog, on_write.value, on_read.value)


async def test_an_error_without_a_sqlstate_is_transient(
    caplog: pytest.LogCaptureFixture, reported: list[BaseException]
) -> None:
    caplog.set_level(logging.DEBUG)

    with pytest.raises(OrderEmailFailed) as raised:
        await write(
            FailingStoreSession(None)
        )  # e.g. InterfaceError, a dropped connection

    assert str(raised.value) == "DBAPIError"
    assert raised.value.__suppress_context__
    assert reported == []
    assert_no_address(caplog, raised.value)


@pytest.mark.parametrize("sqlstate", ["42501", "23514", "23505", "XX000"])
async def test_any_other_error_is_reported_and_the_change_still_commits(
    sqlstate: str, caplog: pytest.LogCaptureFixture, reported: list[BaseException]
) -> None:
    caplog.set_level(logging.DEBUG)

    assert (
        await write(FailingStoreSession(sqlstate)),
        await read(FailingStoreSession(sqlstate)),
    ) == ([], [])

    assert [str(error) for error in reported] == [f"DBAPIError sqlstate={sqlstate}"] * 2
    skipped = [r for r in caplog.records if "order email skipped" in r.getMessage()]
    # A warning: the one Sentry event is the report, not a second one from an ERROR log.
    assert [r.levelno for r in skipped] == [logging.WARNING] * 2
    assert_no_address(caplog, *reported)
