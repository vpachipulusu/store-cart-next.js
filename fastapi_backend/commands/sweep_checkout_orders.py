"""Cancel long expired pending checkout orders in every ACTIVE store (KAN-256).

    uv run python -m commands.sweep_checkout_orders [--batch-size N]

The backstop for a lost ``checkout.session.expired`` event; checkout also sweeps a few orders
of its own store each time it starts. Each store is swept page by page (``--batch-size`` orders
per page, at most ``MAX_PAGES`` pages). An order whose Stripe session is not confirmed expired
is left pending (see ``store_checkout_expiry``), so STRIPE_SECRET_KEY must be set for orders
that have a session. Safe to run at any frequency. A store that cannot be reached is reported
and skipped, the others are still swept; the exit code is 1 if any failed. Output names stores
by id only, never by connection string.
"""

import argparse
import asyncio
import contextlib
import sys
from collections.abc import Sequence

from sqlalchemy import select

from app.core.database import (
    DefaultSessionProvider,
    SessionProvider,
    async_session_maker,
)
from app.core.database import engine as platform_engine
from app.core.stripe_billing import StripeNotConfigured
from app.core.stripe_checkout import StripeCheckout, get_stripe_checkout
from app.models.platform.organization import Organization
from app.models.platform.store import Store
from app.services.store_checkout_expiry import (
    SWEEP_BATCH,
    SweepCursor,
    sweep_expired_checkout_orders,
)
from app.services.store_migrations import (
    DEFAULT_BATCH_SIZE,
    MAX_BATCH_SIZE,
    active_store_pages,
    safe_reason,
)
from app.services.store_sessions import open_store_session

MAX_PAGES = 50  # per store and run: a backlog beyond this waits for the next run


async def connected_account(store_id: str, provider: SessionProvider) -> str | None:
    async with provider.session() as session:
        return (
            await session.execute(
                select(Organization.stripe_connect_account_id)
                .join(Store, Store.organization_id == Organization.id)
                .where(Store.id == store_id)
            )
        ).scalar_one_or_none()


async def sweep_store(
    store_id: str,
    provider: SessionProvider,
    stripe: StripeCheckout | None,
    batch: int = SWEEP_BATCH,
) -> int:
    """Cancelled orders of one store, paging until a short page or ``MAX_PAGES``."""
    account_id = await connected_account(store_id, provider)
    cancelled = 0
    cursor: SweepCursor | None = None
    async with open_store_session(store_id, provider) as session:
        for _ in range(MAX_PAGES):
            page = await sweep_expired_checkout_orders(
                session, stripe, account_id, batch=batch, after=cursor
            )
            cancelled += page.cancelled
            cursor = page.cursor
            if page.examined < batch:
                break
    return cancelled


async def sweep_active_stores(
    provider: SessionProvider, stripe: StripeCheckout | None, batch_size: int
) -> tuple[list[str], int]:
    """Report lines and the number of stores that failed."""
    lines: list[str] = []
    failed = 0
    async for page in active_store_pages(provider, DEFAULT_BATCH_SIZE):
        for store_id in page:
            try:
                cancelled = await sweep_store(store_id, provider, stripe, batch_size)
            except Exception as exc:  # noqa: BLE001 - one store must not stop the rest
                failed += 1
                lines.append(f"FAILED store {store_id}: {safe_reason(exc)}")
                continue
            if cancelled:
                lines.append(f"store {store_id}: cancelled {cancelled} order(s)")
    return lines, failed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sweep expired checkout orders.")
    parser.add_argument("--batch-size", type=int, default=SWEEP_BATCH)
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= MAX_BATCH_SIZE:
        parser.error(f"--batch-size must be between 1 and {MAX_BATCH_SIZE}")
    return args


def _stripe_or_none() -> StripeCheckout | None:
    try:
        return get_stripe_checkout()
    except StripeNotConfigured:
        return None


async def _run(batch_size: int) -> tuple[list[str], int]:
    try:
        return await sweep_active_stores(
            DefaultSessionProvider(async_session_maker), _stripe_or_none(), batch_size
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
