"""Cancel long expired pending checkout orders in every ACTIVE store (KAN-256).

    uv run python -m commands.sweep_checkout_orders [--batch-size N]

The backstop for a lost ``checkout.session.expired`` event; checkout also sweeps its own store
each time it starts. Safe to run any number of times, at any frequency. A store that cannot be
reached is reported and skipped, the others are still swept; the exit code is 1 if any failed.
Output names stores by id only, never by connection string.
"""

import argparse
import asyncio
import contextlib
import sys
from collections.abc import Sequence

from app.core.database import (
    DefaultSessionProvider,
    SessionProvider,
    async_session_maker,
)
from app.core.database import engine as platform_engine
from app.services.store_checkout_expiry import sweep_expired_checkout_orders
from app.services.store_migrations import (
    DEFAULT_BATCH_SIZE,
    MAX_BATCH_SIZE,
    _active_store_pages,
    safe_reason,
)
from app.services.store_sessions import open_store_session


async def sweep_store(store_id: str, provider: SessionProvider) -> int:
    async with open_store_session(store_id, provider) as session:
        cancelled = await sweep_expired_checkout_orders(session)
        await session.commit()
    return cancelled


async def sweep_active_stores(
    provider: SessionProvider, batch_size: int
) -> tuple[list[str], int]:
    """Report lines and the number of stores that failed."""
    lines: list[str] = []
    failed = 0
    async for page in _active_store_pages(provider, batch_size):
        for store_id in page:
            try:
                cancelled = await sweep_store(store_id, provider)
            except Exception as exc:  # noqa: BLE001 - one store must not stop the rest
                failed += 1
                lines.append(f"FAILED store {store_id}: {safe_reason(exc)}")
                continue
            if cancelled:
                lines.append(f"store {store_id}: cancelled {cancelled} order(s)")
    return lines, failed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sweep expired checkout orders.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= MAX_BATCH_SIZE:
        parser.error(f"--batch-size must be between 1 and {MAX_BATCH_SIZE}")
    return args


async def _run(batch_size: int) -> tuple[list[str], int]:
    try:
        return await sweep_active_stores(
            DefaultSessionProvider(async_session_maker), batch_size
        )
    finally:
        with contextlib.suppress(Exception):  # never mask the real error
            await platform_engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        lines, failed = asyncio.run(_run(args.batch_size))
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED (platform or configuration): {safe_reason(exc)}")
        return 1
    for line in lines:
        print(line)
    print(f"swept; {failed} store(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
