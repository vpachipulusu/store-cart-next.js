"""Scheduled purge of expired carts (KAN-252). No FastAPI imports.

Expired carts used to be removed only while a new cart was created (20 at a time), so a store that
stopped taking new carts kept its expired rows. A QStash schedule now calls
``POST /internal/carts/purge`` (see ``docs/developer/backend-storefront-cart.md``) and each run:

* visits at most ``STORES_PER_RUN`` ACTIVE stores, picked at random so every store is reached over
  successive runs;
* deletes at most ``EXPIRED_CARTS_PER_STORE`` expired carts in each (the rest wait for the next run);
* stops starting new stores after ``RUN_TIME_BUDGET_SECONDS`` and cuts off a store still running
  when the budget ends (counted in ``stores_failed``);
* never lets one store stop the others: a store that cannot be opened or queried is counted in
  ``stores_failed`` and logged by exception class and store id only (never a connection string).
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.core.database import SessionProvider
from app.core.sentry import report_exception
from app.repositories.store_cart import StoreCartRepository
from app.repositories.storefront import StorefrontRepository
from app.services.store_sessions import open_store_session

logger = logging.getLogger("storecart.cart_purge")

PURGE_PATH = "/internal/carts/purge"
STORES_PER_RUN = 50
EXPIRED_CARTS_PER_STORE = 1000
# A run stops starting new stores after this long, so it ends before a serverless time limit.
RUN_TIME_BUDGET_SECONDS = 20.0


@dataclass(frozen=True)
class PurgeSummary:
    stores: int
    carts_deleted: int
    stores_failed: int


async def _purge_store(store_id: str, provider: SessionProvider, batch: int) -> int:
    async with open_store_session(store_id, provider) as session:
        deleted = await StoreCartRepository(session).delete_expired_carts(limit=batch)
        await session.commit()
    return deleted


async def purge_expired_carts(
    provider: SessionProvider,
    *,
    max_stores: int = STORES_PER_RUN,
    batch: int = EXPIRED_CARTS_PER_STORE,
    time_budget_seconds: float = RUN_TIME_BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> PurgeSummary:
    """One bounded purge run over a random sample of ACTIVE stores.

    ``stores`` in the summary counts the stores visited; the remaining ones wait for the next run
    when the time budget ends the run early.
    """
    async with provider.session() as platform:
        store_ids = await StorefrontRepository(platform).sample_active_store_ids(
            max_stores
        )
    deadline = clock() + time_budget_seconds
    visited = 0
    deleted = 0
    failed = 0
    for store_id in store_ids:
        remaining = deadline - clock()
        if remaining <= 0:
            break
        visited += 1
        try:
            # A store that hangs (cold database, lock wait) is cut off at the end of the budget.
            async with asyncio.timeout(remaining):
                deleted += await _purge_store(store_id, provider, batch)
        except Exception as exc:  # noqa: BLE001 - one store must not stop the run
            failed += 1
            logger.warning(
                "cart purge failed for a store: error=%s",
                type(exc).__name__,
                extra={"store_id": store_id},
            )
            report_exception(exc)
    logger.info(
        "cart purge finished: stores=%d deleted=%d failed=%d",
        visited,
        deleted,
        failed,
    )
    return PurgeSummary(stores=visited, carts_deleted=deleted, stores_failed=failed)
