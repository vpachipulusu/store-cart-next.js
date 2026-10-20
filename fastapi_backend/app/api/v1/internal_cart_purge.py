"""QStash schedule callback that purges expired carts (KAN-252).

A public route like the provisioning callbacks: no service key, the ``Upstash-Signature`` JWT is
the credential. It must sign this exact URL, so a delivery meant for another QStash route cannot be
replayed here. Not in the OpenAPI schema: only the QStash schedule calls it.

``POST /internal/carts/purge``: run one bounded purge (``app.services.store_cart_purge``). 200 with
the counts; an unexpected failure is a 500, which makes QStash retry (the purge is idempotent).
"""

from collections.abc import Awaitable, Callable
from functools import partial
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from app.api.deps import get_session_provider
from app.api.v1.internal_provisioning import verified_qstash_body
from app.core.database import SessionProvider
from app.services.store_cart_purge import PURGE_PATH, PurgeSummary, purge_expired_carts

router = APIRouter(prefix="/internal/carts", tags=["internal"], include_in_schema=False)

ALL_FAILED_MESSAGE = "Cart purge failed for every store"
CartPurger = Callable[[], Awaitable[PurgeSummary]]


class PurgeResult(BaseModel):
    stores: int
    carts_deleted: int
    stores_failed: int


def get_cart_purger(
    provider: Annotated[SessionProvider, Depends(get_session_provider)],
) -> CartPurger:
    return partial(purge_expired_carts, provider)


@router.post("/purge", response_model=PurgeResult)
async def purge_carts(
    request: Request,
    purger: Annotated[CartPurger, Depends(get_cart_purger)],
    signature: Annotated[str | None, Header(alias="Upstash-Signature")] = None,
) -> PurgeResult:
    """Delete a bounded batch of expired carts from a sample of active stores."""
    await verified_qstash_body(request, signature, PURGE_PATH)
    summary = await purger()
    if summary.stores and summary.stores_failed == summary.stores:
        # Every store failed (platform or network trouble): let QStash retry and alert.
        raise HTTPException(500, ALL_FAILED_MESSAGE)
    return PurgeResult(
        stores=summary.stores,
        carts_deleted=summary.carts_deleted,
        stores_failed=summary.stores_failed,
    )
