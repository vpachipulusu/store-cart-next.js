"""The checkout expiry sweep command (KAN-256), without a database."""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.core.database import SessionProvider
from commands import sweep_checkout_orders
from commands.sweep_checkout_orders import (
    main,
    parse_args,
    sweep_active_stores,
)


def test_batch_size_must_be_positive() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--batch-size", "0"])
    assert parse_args([]).batch_size == 50


async def _pages(*pages: list[str]) -> AsyncIterator[list[str]]:
    for page in pages:
        yield page


async def test_each_store_is_swept_and_one_failure_does_not_stop_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    swept: list[str] = []

    async def sweep_store(store_id: str, provider: SessionProvider) -> int:
        if store_id == "s2":
            raise RuntimeError("password=hunter2 host=db.internal")
        swept.append(store_id)
        return 3 if store_id == "s1" else 0

    monkeypatch.setattr(
        sweep_checkout_orders,
        "_active_store_pages",
        lambda provider, size: _pages(["s1", "s2"], ["s3"]),
    )
    monkeypatch.setattr(sweep_checkout_orders, "sweep_store", sweep_store)

    lines, failed = await sweep_active_stores(object(), 2)  # type: ignore[arg-type]

    assert swept == ["s1", "s3"]
    assert failed == 1
    assert lines[0] == "store s1: cancelled 3 order(s)"
    assert lines[1].startswith("FAILED store s2: ")
    assert "hunter2" not in " ".join(lines)
    assert len(lines) == 2  # s3 cancelled nothing, so it is not listed


@pytest.mark.parametrize(("failed", "code"), [(0, 0), (2, 1)])
def test_the_exit_code_reflects_failed_stores(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failed: int,
    code: int,
) -> None:
    async def run(batch_size: int) -> tuple[list[str], int]:
        return ["store s1: cancelled 1 order(s)"], failed

    monkeypatch.setattr(sweep_checkout_orders, "_run", run)

    assert main([]) == code
    output = capsys.readouterr().out
    assert "store s1: cancelled 1 order(s)" in output
    assert f"swept; {failed} store(s) failed" in output


def test_a_platform_failure_exits_one_without_leaking_the_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def run(batch_size: int) -> Any:
        raise RuntimeError("postgresql://user:secret@host/db")

    monkeypatch.setattr(sweep_checkout_orders, "_run", run)

    assert main([]) == 1
    output = capsys.readouterr().out
    assert output.startswith("FAILED (platform or configuration): ")
    assert "secret" not in output
