"""Move every existing store onto its own database role (KAN-238).

    uv run python -m commands.backfill_store_roles [--store-id ID ...]

An owner step, run once per environment after KAN-238 is deployed, with the platform
``DATABASE_URL`` and ``STORE_DB_ENCRYPTION_KEY`` of that environment. Never from CI or a
deploy. Stops at the first failing store and exits 1; re-running is safe (stores already
moved are skipped). Output names stores by id only, never by connection string.
"""

import argparse
import asyncio
import contextlib
import sys
from collections.abc import Sequence

from app.core.database import engine as platform_engine
from app.services.store_migrations import safe_reason
from app.services.store_role_backfill import BackfillReport, backfill_store_roles


def format_report(report: BackfillReport) -> list[str]:
    lines = [f"store {store_id}: moved to its own role" for store_id in report.moved]
    lines += [
        f"store {store_id}: skipped (already on its own role or not provisioned)"
        for store_id in report.skipped
    ]
    if report.failed_store_id is not None:
        lines.append(
            f"FAILED store {report.failed_store_id}: {report.failure_reason}; "
            "stopped, later stores were not changed"
        )
    failed = 0 if report.succeeded else 1
    lines.append(
        f"moved {len(report.moved)} store(s), skipped {len(report.skipped)}, "
        f"{failed} failed"
    )
    return lines


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Give every store database its own Postgres role."
    )
    parser.add_argument(
        "--store-id",
        action="append",
        dest="store_ids",
        help="only this store (repeatable); default: every provisioned store",
    )
    return parser.parse_args(argv)


async def _run(store_ids: Sequence[str] | None) -> BackfillReport:
    try:
        return await backfill_store_roles(store_ids=store_ids)
    finally:
        with contextlib.suppress(Exception):  # never mask the real error
            await platform_engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = asyncio.run(_run(args.store_ids))
    except Exception as exc:  # noqa: BLE001
        # The platform query failed before any store was touched.
        print(f"FAILED (platform or configuration): {safe_reason(exc)}")
        return 1
    for line in format_report(report):
        print(line)
    return 0 if report.succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
