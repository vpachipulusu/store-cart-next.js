"""Dependency that opens the caller's own store database for the catalogue routes (KAN-245), the order routes (KAN-79) and the public cart (KAN-76).

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

from app.api.deps import SessionDep, get_session_provider
from app.api.merchant import require_merchant
from app.core.database import SessionProvider
from app.core.plans import Plan
from app.models.platform.membership import MembershipRole
from app.repositories.merchant import MerchantAccess, MerchantRepository
from app.repositories.store_cart import StoreCartRepository
from app.repositories.store_catalogue import StoreCatalogueRepository
from app.repositories.store_orders import StoreOrdersRepository
from app.repositories.store_settings import StoreSettingsRepository
from app.repositories.storefront import StorefrontRepository
from app.services.merchant import ALL_ROLES
from app.services.merchant_orders import StoreOrdersService
from app.services.plan_limits import plan_for
from app.services.store_cart import StoreCartService
from app.services.store_products import StoreProductsService
from app.services.store_sessions import StoreSessionError, open_store_session
from app.services.store_settings import StoreSettingsService
from app.services.storefront import active_store_id

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
        platform: SessionDep,
    ) -> AsyncIterator[StoreProductsService]:
        store_id = merchant.store.id

        async def plan() -> Plan:
            tier = await MerchantRepository(platform).effective_plan(
                merchant.organization.id
            )
            await platform.rollback()  # do not hold the platform connection
            return plan_for(tier)

        try:
            async with open_store_session(store_id, provider) as session:
                yield StoreProductsService(
                    StoreCatalogueRepository(session), session, store_id, plan
                )
        except StoreSessionError as error:
            # The cause is in the message, so it shows in log lines that drop extras:
            # StoreDatabaseNotConfigured = provisioning never stored a connection string,
            # StoreDatabaseUnavailable = it cannot be decrypted or used (key or URL).
            reason = type(error).__name__
            logger.error(
                "store database unavailable: %s",
                reason,
                extra={"store_id": store_id, "reason": reason},
            )
            raise HTTPException(503, STORE_UNAVAILABLE) from None

    return dependency


def store_orders_service(
    roles: frozenset[MembershipRole] = ALL_ROLES,
) -> Callable[..., AsyncIterator[StoreOrdersService]]:
    """Dependency factory: an orders service on the caller's store database (KAN-79).

    Same trust chain as the products service: the store opened is the one
    ``require_merchant`` resolved from the caller's memberships.
    """
    merchant_dependency = require_merchant(roles)

    async def dependency(
        merchant: Annotated[MerchantAccess, Depends(merchant_dependency)],
        provider: Annotated[SessionProvider, Depends(get_session_provider)],
    ) -> AsyncIterator[StoreOrdersService]:
        store_id = merchant.store.id
        try:
            async with open_store_session(store_id, provider) as session:
                yield StoreOrdersService(StoreOrdersRepository(session), session)
        except StoreSessionError as error:
            reason = type(error).__name__
            logger.error(
                "store database unavailable: %s",
                reason,
                extra={"store_id": store_id, "reason": reason},
            )
            raise HTTPException(503, STORE_UNAVAILABLE) from None

    return dependency


def store_settings_service(
    roles: frozenset[MembershipRole] = ALL_ROLES,
) -> Callable[..., AsyncIterator[StoreSettingsService]]:
    """Dependency factory: a store settings service on the caller's store database."""
    merchant_dependency = require_merchant(roles)

    async def dependency(
        merchant: Annotated[MerchantAccess, Depends(merchant_dependency)],
        provider: Annotated[SessionProvider, Depends(get_session_provider)],
    ) -> AsyncIterator[StoreSettingsService]:
        store_id = merchant.store.id
        try:
            async with open_store_session(store_id, provider) as session:
                yield StoreSettingsService(
                    StoreSettingsRepository(session),
                    session,
                    store_id=store_id,
                    actor_id=merchant.user_id,
                )
        except StoreSessionError as error:
            reason = type(error).__name__
            logger.error(
                "store database unavailable: %s",
                reason,
                extra={"store_id": store_id, "reason": reason},
            )
            raise HTTPException(503, STORE_UNAVAILABLE) from None

    return dependency


async def storefront_cart_service(
    slug: str,
    provider: Annotated[SessionProvider, Depends(get_session_provider)],
) -> AsyncIterator[StoreCartService]:
    """A cart service on the database of the ACTIVE store named by the public ``{slug}`` (KAN-76).

    The slug is resolved on the platform database; any slug that is not a live store (unknown,
    malformed, reserved, suspended) is the same 404. The platform connection is released
    before the store database is opened.
    """
    async with provider.session() as platform:
        store_id = await active_store_id(StorefrontRepository(platform), slug)
    if store_id is None:
        raise HTTPException(404, "Store not found")
    try:
        async with open_store_session(store_id, provider) as session:
            yield StoreCartService(
                StoreCartRepository(session),
                StoreSettingsService(StoreSettingsRepository(session), session),
                session,
            )
    except StoreSessionError as error:
        reason = type(error).__name__
        logger.error(
            "store database unavailable: %s",
            reason,
            extra={"store_id": store_id, "reason": reason},
        )
        raise HTTPException(503, STORE_UNAVAILABLE) from None
