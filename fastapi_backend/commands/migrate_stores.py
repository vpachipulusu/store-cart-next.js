"""Apply pending store migrations to every ACTIVE store (KAN-57).

    uv run python -m commands.migrate_stores [--batch-size N]

Runs from GitHub Actions on deploy (.github/workflows/migrate-stores.yml), never inside
a request. Stops at the first failing store and exits 1; stores after it are untouched.
Output names stores by id only, never by connection string.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence

from app.services.store_migrations import (
    DEFAULT_BATCH_SIZE,
    MigrationReport,
    migrate_active_stores,
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
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = asyncio.run(migrate_active_stores(batch_size=args.batch_size))
    except Exception as exc:  # noqa: BLE001
        # Platform-database errors can carry SQL, parameters or hosts: no traceback.
        print(f"FAILED before or between stores: {type(exc).__name__}")
        return 1
    for line in format_report(report):
        print(line)
    return 0 if report.succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
