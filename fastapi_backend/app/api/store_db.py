"""Dependency that opens the caller's own store database for the catalogue routes (KAN-245), the order routes (KAN-79), the public cart (KAN-76), the public catalogue (KAN-75) and checkout (KAN-68).

The store id is never taken from the request on its own: ``require_merchant`` resolves the
``{store_id}`` path segment against the caller's organisation memberships (404 for any
store they cannot see), and this module opens the database of ``merchant.store.id``, the
id read back from the platform database. The platform session provider is the injectable
seam (``get_session_provider``); the store engine is built and disposed by
``open_store_session``, the only door to a store database.
"""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, get_rate_limiter, get_session_provider
from app.api.merchant import require_merchant
from app.core.config import settings
from app.core.database import SessionProvider
from app.core.plans import Plan
from app.core.rate_limit import CART_CREATE_POLICY, RateLimiter
from app.core.stripe_checkout import StripeCheckout
from app.models.platform.membership import MembershipRole
from app.repositories.app_settings import AppSettingsRepository
from app.repositories.merchant import MerchantAccess, MerchantRepository
from app.repositories.store_analytics import StoreAnalyticsRepository
from app.repositories.store_cart import StoreCartRepository
from app.repositories.store_catalogue import StoreCatalogueRepository
from app.repositories.store_orders import StoreOrdersRepository
from app.repositories.store_settings import StoreSettingsRepository
from app.repositories.storefront import StorefrontRepository
from app.services.merchant import ALL_ROLES
from app.services.merchant_orders import StoreOrdersService
from app.services.plan_limits import plan_for
from app.services.public_settings import PublicSettingsService
from app.services.store_analytics import StoreAnalyticsService
from app.services.store_cart import StoreCartService
from app.services.store_cart_limits import (
    CartCreationGuard,
    CartCreationUnavailable,
    RateLimitedCartCreation,
)
from app.services.store_checkout import (
    PAYMENT_EVENT_TYPES,
    CheckoutOrders,
    PlatformCheckoutTargets,
    SqlCheckoutOrders,
    StoreCheckoutService,
    checkout_payment_handler,
)
from app.services.store_products import StoreProductsService
from app.services.store_sessions import StoreSessionError, open_store_session
from app.services.store_settings import StoreSettingsService
from app.services.storefront import active_store_id
from app.services.storefront_catalogue import StorefrontCatalogueService
from app.services.stripe_connect import StoreEventHandler

logger = logging.getLogger(__name__)

STORE_UNAVAILABLE = "Store database is not available"
NO_STORE_HEADERS = {"Cache-Control": "no-store"}


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


def store_analytics_service(
    roles: frozenset[MembershipRole],
) -> Callable[..., AsyncIterator[StoreAnalyticsService]]:
    """Dependency factory: read-only sales analytics on the caller's store database (KAN-96).

    Same trust chain as the orders service; ``roles`` has no default because the figures are
    revenue data and the route must choose who may see them.
    """
    merchant_dependency = require_merchant(roles)

    async def dependency(
        merchant: Annotated[MerchantAccess, Depends(merchant_dependency)],
        provider: Annotated[SessionProvider, Depends(get_session_provider)],
    ) -> AsyncIterator[StoreAnalyticsService]:
        store_id = merchant.store.id
        try:
            async with open_store_session(store_id, provider) as session:
                yield StoreAnalyticsService(StoreAnalyticsRepository(session))
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


async def _active_store_or_404(platform: AsyncSession, slug: str) -> str:
    """The id of the ACTIVE store named by the public ``{slug}``; any other slug is the same 404."""
    store_id = await active_store_id(StorefrontRepository(platform), slug)
    if store_id is None:
        raise HTTPException(404, "Store not found", headers=NO_STORE_HEADERS)
    return store_id


@asynccontextmanager
async def _open_public_store(
    store_id: str, provider: SessionProvider
) -> AsyncIterator[AsyncSession]:
    """The store database for a public route; a store without a usable database is a 503."""
    try:
        async with open_store_session(store_id, provider) as session:
            yield session
    except StoreSessionError as error:
        reason = type(error).__name__
        logger.error(
            "store database unavailable: %s",
            reason,
            extra={"store_id": store_id, "reason": reason},
        )
        raise HTTPException(503, STORE_UNAVAILABLE, headers=NO_STORE_HEADERS) from None


class NoCartCreation:
    """For callers that only read or price an existing cart (checkout): starting one is refused."""

    async def admit(self) -> None:
        raise CartCreationUnavailable


def _cart_service(
    session: AsyncSession, creation: CartCreationGuard
) -> StoreCartService:
    return StoreCartService(
        StoreCartRepository(session),
        StoreSettingsService(StoreSettingsRepository(session), session),
        session,
        creation,
    )


def storefront_checkout_service(
    provider: SessionProvider,
    stripe: StripeCheckout,
    origins: frozenset[str],
    root_domain: str | None,
) -> StoreCheckoutService:
    """A checkout service for public storefront routes (KAN-68).

    The store is resolved from the public slug on the platform database (ACTIVE only), then its
    own database is opened for the cart and the order. A store database that cannot be opened
    raises ``StoreSessionError`` from inside ``start``; the route maps it to 503.
    """

    @asynccontextmanager
    async def open_orders(store_id: str) -> AsyncIterator[CheckoutOrders]:
        async with open_store_session(store_id, provider) as session:
            yield SqlCheckoutOrders(
                session,
                _cart_service(session, NoCartCreation()),
                StoreSettingsService(StoreSettingsRepository(session), session),
            )

    return StoreCheckoutService(
        PlatformCheckoutTargets(provider), open_orders, stripe, origins, root_domain
    )


def connect_store_handlers(provider: SessionProvider) -> dict[str, StoreEventHandler]:
    """Store-scoped Connect webhook handlers (KAN-68): checkout payments confirm the order."""
    payment = checkout_payment_handler(
        lambda store_id: open_store_session(store_id, provider)
    )
    return dict.fromkeys(PAYMENT_EVENT_TYPES, payment)


async def storefront_cart_service(
    slug: str,
    provider: Annotated[SessionProvider, Depends(get_session_provider)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> AsyncIterator[StoreCartService]:
    """A cart service on the database of the ACTIVE store named by the public ``{slug}`` (KAN-76).

    The platform connection is released before the store database is opened. Starting a cart
    counts against the store's hourly creation cap (KAN-252), keyed by the resolved store id.
    """
    async with provider.session() as platform:
        store_id = await _active_store_or_404(platform, slug)
    creation = RateLimitedCartCreation(limiter, store_id, CART_CREATE_POLICY)
    async with _open_public_store(store_id, provider) as session:
        yield _cart_service(session, creation)


async def storefront_catalogue_service(
    slug: str,
    provider: Annotated[SessionProvider, Depends(get_session_provider)],
) -> AsyncIterator[StorefrontCatalogueService]:
    """Public catalogue reads on the database of the ACTIVE store named by ``{slug}`` (KAN-75).

    The slug and the platform currency are read in one short platform session, released before
    the store database is opened, so a request never holds two pooled connections.
    """
    async with provider.session() as platform:
        store_id = await _active_store_or_404(platform, slug)
        currency = await PublicSettingsService(
            AppSettingsRepository(platform)
        ).currency()
    async with _open_public_store(store_id, provider) as session:
        yield StorefrontCatalogueService(
            StoreCatalogueRepository(session), settings.R2_PUBLIC_BASE_URL, currency
        )
