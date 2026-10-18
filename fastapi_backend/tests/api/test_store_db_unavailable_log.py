"""The 503 for an unusable store database names its cause in the log (KAN-248)."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.store_db import STORE_UNAVAILABLE, store_products_service
from app.services.store_sessions import (
    StoreDatabaseNotConfigured,
    StoreDatabaseUnavailable,
    StoreNotFound,
)

SENTINEL_DSN = "postgresql://sentinel-user:sentinel-pw@db.invalid/secret"


async def _open(monkeypatch: pytest.MonkeyPatch, error: Exception) -> HTTPException:
    @asynccontextmanager
    async def failing(store_id, provider):  # type: ignore[no-untyped-def]
        raise error
        yield

    monkeypatch.setattr("app.api.store_db.open_store_session", failing)
    merchant = SimpleNamespace(
        store=SimpleNamespace(id="store1"), organization=SimpleNamespace(id="org1")
    )
    agen = store_products_service()(merchant, None, None)
    with pytest.raises(HTTPException) as raised:
        await agen.__anext__()
    return raised.value


@pytest.mark.parametrize(
    "error",
    [
        StoreDatabaseNotConfigured("store1"),
        StoreDatabaseUnavailable("store1"),
        StoreNotFound("store1"),
    ],
)
async def test_log_message_names_the_cause_and_the_body_stays_generic(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    error.args = (
        *error.args,
        SENTINEL_DSN,
    )  # a message that echoes a DSN must not be logged
    raised = await _open(monkeypatch, error)

    out = caplog.text
    assert raised.status_code == 503 and raised.detail == STORE_UNAVAILABLE
    assert SENTINEL_DSN not in str(raised.detail)
    assert f"store database unavailable: {type(error).__name__}" in out
    assert SENTINEL_DSN not in out and "sentinel-pw" not in out
