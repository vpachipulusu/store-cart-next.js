import pytest

from app.services.store_role_backfill import BackfillFailure, BackfillReport
from commands import backfill_store_roles
from commands.backfill_store_roles import (
    ROTATE_SHARED_ROLE,
    format_report,
    main,
    parse_args,
    platform_target,
)


def test_report_lists_each_outcome_and_the_rotation_step():
    report = BackfillReport(moved=("s1", "s2"), skipped=("s3",))

    lines = format_report(report)

    assert lines[:2] == [
        "store s1: moved to its own role",
        "store s2: moved to its own role",
    ]
    assert "store s3: skipped (already on its own role or not provisioned)" in lines
    assert "moved 2, would move 0, would repair 0, skipped 1, failed 0" in lines
    assert lines[-1] == ROTATE_SHARED_ROLE


def test_dry_run_lists_stores_that_would_move_and_asks_for_no_rotation():
    lines = format_report(
        BackfillReport(would_move=("s1",), would_repair=("s2",)), dry_run=True
    )

    assert "store s1: would move (dry run)" in lines
    assert "store s2: would repair (dry run): objects still on the shared role" in lines
    assert ROTATE_SHARED_ROLE not in lines


def test_failures_name_only_the_store_and_reason():
    report = BackfillReport(
        moved=("s1",),
        failures=(BackfillFailure("s2", "OwnershipNotMoved"),),
        stopped=True,
    )

    lines = format_report(report)

    assert "FAILED store s2: OwnershipNotMoved" in lines
    assert "stopped at the first failure; later stores were not changed" in lines
    assert "moved 1, would move 0, would repair 0, skipped 0, failed 1" in lines


def test_a_selection_is_required_and_exclusive():
    with pytest.raises(SystemExit):
        parse_args([])
    with pytest.raises(SystemExit):
        parse_args(["--all", "--store-id", "a"])
    assert parse_args(["--all"]).store_ids is None
    args = parse_args(["--store-id", "a", "--store-id", "b", "--dry-run"])
    assert (args.store_ids, args.dry_run, args.continue_on_error) == (
        ["a", "b"],
        True,
        False,
    )


def test_platform_target_shows_host_and_database_but_no_credentials(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        backfill_store_roles.settings,
        "DATABASE_URL",
        "postgresql+asyncpg://owner:hunter2@ep-x.neon.tech/platform",
    )

    target = platform_target()

    assert target == "platform database: host=ep-x.neon.tech database=platform"
    assert "hunter2" not in target and "owner" not in target


@pytest.mark.parametrize(
    ("failures", "code"), [((), 0), ((BackfillFailure("s2", "Boom"),), 1)]
)
def test_exit_code_reflects_the_outcome(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failures: tuple[BackfillFailure, ...],
    code: int,
):
    seen: dict[str, object] = {}

    async def fake(**kwargs: object) -> BackfillReport:
        seen.update(kwargs)
        return BackfillReport(failures=failures)

    monkeypatch.setattr(backfill_store_roles, "backfill_store_roles", fake)

    assert main(["--store-id", "s1", "--continue-on-error"]) == code
    assert seen == {"store_ids": ["s1"], "dry_run": False, "continue_on_error": True}
    assert capsys.readouterr().out.startswith("platform database: host=")


def test_a_platform_failure_exits_1_without_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    async def boom(**kwargs: object) -> BackfillReport:
        raise RuntimeError("postgresql://u:hunter2@host/db")

    monkeypatch.setattr(backfill_store_roles, "backfill_store_roles", boom)

    assert main(["--all"]) == 1
    out = capsys.readouterr().out
    assert "FAILED (platform or configuration): RuntimeError" in out
    assert "hunter2" not in out
