import pytest

from app.models.platform.store import StoreStatus
from app.services.store_migrations import MigrationReport, StoreMigrationResult
from commands import migrate_stores
from commands.migrate_stores import format_report, main, parse_args


def test_report_lists_each_store_skips_and_the_total():
    report = MigrationReport(
        migrated=(StoreMigrationResult("s1", 1), StoreMigrationResult("s2", 3)),
        skipped={StoreStatus.SUSPENDED: 2, StoreStatus.PROVISIONING: 1},
    )

    lines = format_report(report)

    assert lines[0] == "store s1: schema version 1"
    assert lines[1] == "store s2: schema version 3"
    assert "skipped 1 store(s) with status PROVISIONING (not ACTIVE)" in lines
    assert "skipped 2 store(s) with status SUSPENDED (not ACTIVE)" in lines
    assert lines[-1] == "migrated 2 store(s), 0 failed"


def test_failure_line_names_only_the_store_and_reason():
    report = MigrationReport(
        migrated=(StoreMigrationResult("s1", 1),),
        failed_store_id="s2",
        failure_reason="OperationalError",
    )

    lines = format_report(report)

    assert (
        "FAILED store s2: OperationalError; stopped, later stores were not migrated"
        in lines
    )
    assert lines[-1] == "migrated 1 store(s), 1 failed"


def test_batch_size_must_be_positive():
    with pytest.raises(SystemExit):
        parse_args(["--batch-size", "0"])
    assert parse_args([]).batch_size == 50


@pytest.mark.parametrize(("failed", "code"), [(None, 0), ("s2", 1)])
def test_exit_code_reflects_the_outcome(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failed: str | None,
    code: int,
):
    seen: dict[str, int] = {}

    async def fake(*, batch_size: int) -> MigrationReport:
        seen["batch_size"] = batch_size
        return MigrationReport(failed_store_id=failed, failure_reason="Boom")

    monkeypatch.setattr(migrate_stores, "migrate_active_stores", fake)

    assert main(["--batch-size", "7"]) == code
    assert seen["batch_size"] == 7
    assert "migrated 0 store(s)" in capsys.readouterr().out


def test_platform_failure_prints_class_and_sqlstate_but_no_traceback_or_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    class Driver(Exception):
        sqlstate = "08006"

    class OperationalError(Exception):
        orig = Driver("connection to postgresql://u:hunter2@h/db failed")

    async def fake(*, batch_size: int) -> MigrationReport:
        raise OperationalError("SELECT ... postgresql://u:hunter2@h/db")

    monkeypatch.setattr(migrate_stores, "migrate_active_stores", fake)

    assert main([]) == 1
    out = capsys.readouterr().out
    assert "OperationalError sqlstate=08006" in out
    assert "hunter2" not in out
    assert "Traceback" not in out


def test_batch_size_is_capped():
    with pytest.raises(SystemExit):
        parse_args(["--batch-size", "501"])
    assert parse_args(["--batch-size", "500"]).batch_size == 500
