"""Apply pending store migrations to every ACTIVE store (KAN-57).

    uv run python -m commands.migrate_stores [--batch-size N]

Runs from GitHub Actions on deploy (.github/workflows/migrate-stores.yml), never inside
a request. Stops at the first failing store and exits 1; stores after it are untouched.
Output names stores by id only, never by connection string.
"""

import argparse
import asyncio
import contextlib
import sys
from collections.abc import Sequence

from app.core.database import engine as platform_engine
from app.services.store_migrations import (
    DEFAULT_BATCH_SIZE,
    MAX_BATCH_SIZE,
    MigrationReport,
    migrate_active_stores,
    safe_reason,
)


def format_report(report: MigrationReport) -> list[str]:
    lines = [
        f"store {result.store_id}: schema version {result.schema_version}"
        for result in report.migrated
    ]
    for status, count in sorted(report.skipped.items()):
        lines.append(
            f"skipped {count} store(s) with status {status.value} (not ACTIVE)"
        )
    if report.failed_store_id is not None:
        lines.append(
            f"FAILED store {report.failed_store_id}: {report.failure_reason}; "
            "stopped, later stores were not migrated"
        )
    failed = 0 if report.succeeded else 1
    lines.append(f"migrated {len(report.migrated)} store(s), {failed} failed")
    return lines


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate every ACTIVE store database.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= MAX_BATCH_SIZE:
        parser.error(f"--batch-size must be between 1 and {MAX_BATCH_SIZE}")
    return args


async def _run(batch_size: int) -> MigrationReport:
    try:
        return await migrate_active_stores(batch_size=batch_size)
    finally:
        # Close the platform engine while the event loop is still running.
        with contextlib.suppress(Exception):  # never mask the real error
            await platform_engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = asyncio.run(_run(args.batch_size))
    except Exception as exc:  # noqa: BLE001
        # Not a store-level failure (those are reported per store in the report). The
        # platform database holds no store connection strings, so the class name and
        # SQLSTATE are safe to show; the traceback and message (SQL, hosts) are not.
        print(f"FAILED (platform or configuration): {safe_reason(exc)}")
        return 1
    for line in format_report(report):
        print(line)
    return 0 if report.succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
