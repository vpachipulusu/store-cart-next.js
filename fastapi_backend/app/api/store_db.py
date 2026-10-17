"""Dependency that opens the caller's own store database for the catalogue routes (KAN-245).

The store id is never taken from the request on its own: ``require_merchant`` resolves the
``{store_id}`` path segment against the caller's organisation memberships (404 for any
store they cannot see), and this module opens the database of ``merchant.store.id``, the
id read back from the platform database. The platform session provider is the injectable
seam (``get_session_provider``); the store engine is built and disposed by
``open_store_session``, the only door to a store database.
"""

import logging
from collections.abc import AsyncIterator, Callable
from typing import Annotated

from fastapi import Depends, HTTPException

from app.api.deps import get_session_provider
from app.api.merchant import require_merchant
from app.core.database import SessionProvider
from app.models.platform.membership import MembershipRole
from app.repositories.merchant import MerchantAccess
from app.repositories.store_catalogue import StoreCatalogueRepository
from app.services.merchant import ALL_ROLES
from app.services.store_products import StoreProductsService
from app.services.store_sessions import StoreSessionError, open_store_session

logger = logging.getLogger(__name__)

STORE_UNAVAILABLE = "Store database is not available"


def store_products_service(
    roles: frozenset[MembershipRole] = ALL_ROLES,
) -> Callable[..., AsyncIterator[StoreProductsService]]:
    """Dependency factory: a products service on the caller's store database.

    Non-GET requests are writes, so ``require_merchant`` also demands an ACTIVE store.
    """
    merchant_dependency = require_merchant(roles)

    async def dependency(
        merchant: Annotated[MerchantAccess, Depends(merchant_dependency)],
        provider: Annotated[SessionProvider, Depends(get_session_provider)],
    ) -> AsyncIterator[StoreProductsService]:
        store_id = merchant.store.id
        try:
            async with open_store_session(store_id, provider) as session:
                yield StoreProductsService(
                    StoreCatalogueRepository(session), session, store_id
                )
        except StoreSessionError as error:
            logger.error(
                "store database unavailable",
                extra={"store_id": store_id, "reason": type(error).__name__},
            )
            raise HTTPException(503, STORE_UNAVAILABLE) from None

    return dependency
