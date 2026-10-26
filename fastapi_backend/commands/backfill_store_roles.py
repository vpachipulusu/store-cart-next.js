"""Move existing stores onto their own database role (KAN-238).

    uv run python -m commands.backfill_store_roles (--all | --store-id ID ...)
        [--dry-run] [--continue-on-error]

An owner step, run once per environment after KAN-238 is deployed, with that
environment's platform ``DATABASE_URL`` and ``STORE_DB_ENCRYPTION_KEY``, and with
``migrate_stores`` and provisioning paused. Never from CI or a deploy. ``--all`` takes
every ACTIVE and PROVISIONING store with a database; ``--dry-run`` checks and lists the
stores that would move without changing anything. It stops at the first failing store
unless ``--continue-on-error``, and exits 1 when any store failed. Re-running is safe
(stores already moved are skipped). Output names stores by id and the platform database
by host and name only, never credentials.

Afterwards, reset the shared role's (``NEON_ROLE_NAME``) password: every connection
string written before KAN-238 still carries it (ADR-005).
"""

import argparse
import asyncio
import contextlib
import sys
from collections.abc import Sequence

from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.database import engine as platform_engine
from app.services.store_migrations import safe_reason
from app.services.store_role_backfill import BackfillReport, backfill_store_roles

ROTATE_SHARED_ROLE = (
    "REQUIRED NEXT STEP: reset the NEON_ROLE_NAME password (Neon console or API) and "
    "update NEON_ROLE_NAME's credentials wherever the backend reads them; if the "
    "platform DATABASE_URL signs in as the same role, update it too. Until then every "
    "connection string written before KAN-238 (and any copy of one) still opens every "
    "store."
)


def platform_target() -> str:
    """Host and database of the platform database: never the user or password."""
    url = make_url(settings.DATABASE_URL)
    return f"platform database: host={url.host} database={url.database}"


def format_report(report: BackfillReport, *, dry_run: bool = False) -> list[str]:
    lines = [f"store {store_id}: moved to its own role" for store_id in report.moved]
    lines += [
        f"store {store_id}: would move (dry run)" for store_id in report.would_move
    ]
    lines += [
        f"store {store_id}: skipped (already on its own role or not provisioned)"
        for store_id in report.skipped
    ]
    lines += [
        f"FAILED store {failure.store_id}: {failure.reason}"
        for failure in report.failures
    ]
    if report.stopped:
        lines.append("stopped at the first failure; later stores were not changed")
    lines.append(
        f"moved {len(report.moved)}, would move {len(report.would_move)}, "
        f"skipped {len(report.skipped)}, failed {len(report.failures)}"
    )
    if report.moved and not dry_run:
        lines.append(ROTATE_SHARED_ROLE)
    return lines


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Give every store database its own Postgres role."
    )
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument(
        "--all",
        action="store_true",
        help="every ACTIVE and PROVISIONING store with a database",
    )
    which.add_argument(
        "--store-id",
        action="append",
        dest="store_ids",
        help="only this store (repeatable)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="check and list; change nothing"
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="go on after a failing store (the exit code is still 1)",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> BackfillReport:
    try:
        return await backfill_store_roles(
            store_ids=args.store_ids,
            dry_run=args.dry_run,
            continue_on_error=args.continue_on_error,
        )
    finally:
        with contextlib.suppress(Exception):  # never mask the real error
            await platform_engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    print(platform_target())
    try:
        report = asyncio.run(_run(args))
    except Exception as exc:  # noqa: BLE001
        # The platform query failed before any store was touched.
        print(f"FAILED (platform or configuration): {safe_reason(exc)}")
        return 1
    for line in format_report(report, dry_run=args.dry_run):
        print(line)
    return 0 if report.succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
