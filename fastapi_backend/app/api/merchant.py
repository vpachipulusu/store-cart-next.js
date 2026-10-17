"""Merchant authorisation dependency (KAN-52).

Usage in a store route::

    @router.get("/v1/stores/{store_id}/products")
    async def list_products(
        merchant: Annotated[MerchantAccess, Depends(require_merchant())],
    ): ...

    @router.post("/v1/stores/{store_id}/products")
    async def create_product(
        merchant: Annotated[
            MerchantAccess, Depends(require_merchant(OWNER_ADMIN, write=True))
        ],
    ): ...

The route path must declare ``{store_id}``. Authentication is the existing chain
(internal key, verified session); authorisation re-reads the membership table.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request

from app.api.auth import get_current_identity
from app.api.deps import SessionDep
from app.core.firebase import VerifiedIdentity
from app.models.platform.membership import MembershipRole
from app.repositories.merchant import MerchantAccess, MerchantRepository
from app.services.merchant import (
    ALL_ROLES,
    MerchantForbidden,
    MerchantService,
    StoreNotFound,
    StoreSuspended,
)

logger = logging.getLogger(__name__)

OWNER_ADMIN = frozenset({MembershipRole.OWNER, MembershipRole.ADMIN})
NOT_FOUND = "Store not found"
FORBIDDEN = "Forbidden"
SUSPENDED = "Store is not active"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MAX_STORE_ID_LENGTH = 128


def get_merchant_service(session: SessionDep) -> MerchantService:
    return MerchantService(MerchantRepository(session), session)


MerchantServiceDep = Annotated[MerchantService, Depends(get_merchant_service)]


def require_merchant(
    roles: frozenset[MembershipRole] = ALL_ROLES,
    *,
    write: bool = False,
    any_status: bool = False,
) -> Callable[..., Awaitable[MerchantAccess]]:
    """Dependency factory: the caller holds one of ``roles`` in the store's organisation.

    ``write=True`` also requires an ACTIVE store (see ``app.services.merchant``). Any
    request whose method is not GET, HEAD or OPTIONS is treated as a write whatever the
    flag says, so a forgotten ``write=True`` cannot let a mutation through on a
    suspended store. ``any_status=True`` is for the one route that acts on a store that
    is not ACTIVE (retrying a FAILED store, KAN-242): the role is still checked, the
    status is left to the route.
    Returns the user id, organisation, store and role. 404 is the same body whether
    the store is unknown or belongs to someone else.
    """
    if not roles:
        raise ValueError("require_merchant needs at least one role")
    allowed = frozenset(roles)

    async def dependency(
        request: Request,
        store_id: Annotated[str, Path()],
        identity: Annotated[VerifiedIdentity, Depends(get_current_identity)],
        service: MerchantServiceDep,
    ) -> MerchantAccess:
        if not store_id or len(store_id) > MAX_STORE_ID_LENGTH or "\0" in store_id:
            raise HTTPException(404, NOT_FOUND)
        is_write = (write or request.method not in SAFE_METHODS) and not any_status
        try:
            return await service.authorize(
                store_id, identity.uid, allowed, write=is_write
            )
        except StoreNotFound:
            raise HTTPException(404, NOT_FOUND) from None
        except MerchantForbidden:
            logger.warning(
                "merchant access denied: role", extra={"firebase_uid": identity.uid}
            )
            raise HTTPException(403, FORBIDDEN) from None
        except StoreSuspended:
            logger.warning(
                "merchant write denied: store status",
                extra={"firebase_uid": identity.uid},
            )
            raise HTTPException(403, SUSPENDED) from None

    return dependency
