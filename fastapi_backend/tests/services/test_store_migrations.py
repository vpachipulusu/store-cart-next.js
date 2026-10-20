import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest
from alembic.script import ScriptDirectory

from app.models.platform.store import StoreStatus
from app.services import store_migrations
from app.services.store_migrations import (
    STORE_SCRIPT_LOCATION,
    MigrationReport,
    StoreMigrationFailed,
    StoreMigrationResult,
    _alembic_config,
    migrate_active_stores,
    migrate_pages,
    migrate_store,
)

DSN = "postgresql://user:hunter2@ep-x-pooler.neon.tech/store?sslmode=require"


async def pages_of(*pages: list[str]) -> AsyncIterator[list[str]]:
    for page in pages:
        yield page


def test_store_tree_has_a_single_head_and_a_baseline():
    scripts = ScriptDirectory.from_config(_alembic_config(STORE_SCRIPT_LOCATION))

    assert scripts.get_heads() == ["0009"]
    assert scripts.get_revision("0001").down_revision is None
    assert scripts.get_revision("0002").down_revision == "0001"
    assert scripts.get_revision("0003").down_revision == "0002"
    assert scripts.get_revision("0004").down_revision == "0003"
    assert scripts.get_revision("0005").down_revision == "0004"
    assert scripts.get_revision("0006").down_revision == "0005"
    assert scripts.get_revision("0007").down_revision == "0006"
    assert scripts.get_revision("0008").down_revision == "0007"
    assert scripts.get_revision("0009").down_revision == "0008"


async def test_migrate_pages_migrates_every_store_across_pages():
    seen: list[str] = []

    async def migrate(store_id: str) -> int:
        seen.append(store_id)
        return 1

    migrated, failure = await migrate_pages(pages_of(["a", "b"], ["c"]), migrate)

    assert failure is None
    assert seen == ["a", "b", "c"]
    assert migrated == (
        StoreMigrationResult("a", 1),
        StoreMigrationResult("b", 1),
        StoreMigrationResult("c", 1),
    )


async def test_migrate_pages_stops_at_the_first_failure():
    seen: list[str] = []

    async def migrate(store_id: str) -> int:
        seen.append(store_id)
        if store_id == "b":
            raise StoreMigrationFailed("b", "OperationalError")
        return 2

    migrated, failure = await migrate_pages(pages_of(["a", "b"], ["c"]), migrate)

    assert seen == ["a", "b"]
    assert migrated == (StoreMigrationResult("a", 2),)
    assert failure is not None
    assert failure.store_id == "b"


async def test_migrate_store_failure_names_only_the_store_and_error_class(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    def leaky(*_: Any, **__: Any) -> Any:
        raise RuntimeError(f"could not connect to {DSN}")

    monkeypatch.setattr(store_migrations, "open_store_session", leaky)

    with (
        caplog.at_level(logging.ERROR, logger="storecart.store_migrations"),
        pytest.raises(StoreMigrationFailed) as caught,
    ):
        await migrate_store("store1234", provider=object())  # type: ignore[arg-type]

    assert caught.value.store_id == "store1234"
    assert "RuntimeError" in str(caught.value)
    everything = str(caught.value) + caplog.text + repr(caught.value.__cause__)
    assert "hunter2" not in everything
    assert "neon.tech" not in everything


async def test_migrate_active_stores_rejects_a_non_positive_batch_size():
    with pytest.raises(ValueError):
        await migrate_active_stores(object(), batch_size=0)  # type: ignore[arg-type]


def test_report_succeeds_only_without_a_failure():
    assert MigrationReport().succeeded
    assert not MigrationReport(failed_store_id="x", failure_reason="Boom").succeeded
    assert MigrationReport(skipped={StoreStatus.SUSPENDED: 1}).succeeded


async def test_failure_reason_carries_sqlstate_but_never_the_message(
    monkeypatch: pytest.MonkeyPatch,
):
    class Driver(Exception):
        sqlstate = "55P03"

    class Wrapped(Exception):
        orig = Driver(f"lock failed for {DSN}")

    def failing(*_: Any, **__: Any) -> Any:
        raise Wrapped(DSN)

    monkeypatch.setattr(store_migrations, "open_store_session", failing)

    with pytest.raises(StoreMigrationFailed) as caught:
        await migrate_store("store1234", provider=object())  # type: ignore[arg-type]

    assert caught.value.reason == "Wrapped sqlstate=55P03"
    assert "hunter2" not in str(caught.value)


async def test_migrate_active_stores_rejects_a_batch_size_above_the_cap():
    with pytest.raises(ValueError):
        await migrate_active_stores(object(), batch_size=501)  # type: ignore[arg-type]
