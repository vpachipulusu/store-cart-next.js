import pytest

from app.services.store_role_backfill import BackfillReport
from commands import backfill_store_roles
from commands.backfill_store_roles import format_report, main, parse_args


def test_report_lists_moved_skipped_and_the_total():
    report = BackfillReport(moved=("s1", "s2"), skipped=("s3",))

    lines = format_report(report)

    assert lines[:2] == [
        "store s1: moved to its own role",
        "store s2: moved to its own role",
    ]
    assert "store s3: skipped (already on its own role or not provisioned)" in lines
    assert lines[-1] == "moved 2 store(s), skipped 1, 0 failed"


def test_failure_line_names_only_the_store_and_reason():
    report = BackfillReport(
        moved=("s1",), failed_store_id="s2", failure_reason="OwnershipNotMoved"
    )

    lines = format_report(report)

    assert (
        "FAILED store s2: OwnershipNotMoved; stopped, later stores were not changed"
        in lines
    )
    assert lines[-1] == "moved 1 store(s), skipped 0, 1 failed"


def test_store_ids_are_optional_and_repeatable():
    assert parse_args([]).store_ids is None
    assert parse_args(["--store-id", "a", "--store-id", "b"]).store_ids == ["a", "b"]


@pytest.mark.parametrize(("failed", "code"), [(None, 0), ("s2", 1)])
def test_exit_code_reflects_the_outcome(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failed: str | None,
    code: int,
):
    seen: dict[str, object] = {}

    async def fake(*, store_ids: list[str] | None) -> BackfillReport:
        seen["store_ids"] = store_ids
        return BackfillReport(failed_store_id=failed, failure_reason="Boom")

    monkeypatch.setattr(backfill_store_roles, "backfill_store_roles", fake)

    assert main(["--store-id", "s1"]) == code
    assert seen["store_ids"] == ["s1"]
    assert "failed" in capsys.readouterr().out


def test_a_platform_failure_exits_1_without_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    async def boom(*, store_ids: list[str] | None) -> BackfillReport:
        raise RuntimeError("postgresql://u:hunter2@host/db")

    monkeypatch.setattr(backfill_store_roles, "backfill_store_roles", boom)

    assert main([]) == 1
    out = capsys.readouterr().out
    assert out.strip() == "FAILED (platform or configuration): RuntimeError"
