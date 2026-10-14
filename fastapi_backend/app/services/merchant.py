"""Merchant authorisation (KAN-52): may this caller act on this store, in this role?

The answer comes from the ``memberships`` table on every call; token claims are never
consulted. A store the caller cannot see (unknown id, another organisation's store, or
a caller with no membership) is ``StoreNotFound`` (404), identical in every case. Only a
member of the owning organisation can learn the store exists, and only they can get
``MerchantForbidden`` (wrong role) or ``StoreSuspended``.

Store status policy (documented in docs/developer/backend-auth.md):

* ACTIVE: reads and writes.
* SUSPENDED and PROVISIONING: reads only; writes raise ``StoreSuspended`` (403).
* ARCHIVED: treated as gone, ``StoreNotFound`` (404).
"""

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform.membership import MembershipRole
from app.models.platform.store import StoreStatus
from app.repositories.merchant import MerchantAccess

ALL_ROLES = frozenset(MembershipRole)
WRITABLE_STATUSES = frozenset({StoreStatus.ACTIVE})


class StoreNotFound(Exception):
    """Unknown store, another organisation's store or no membership (404)."""


class MerchantForbidden(Exception):
    """A member whose role is not allowed here (403)."""


class StoreSuspended(Exception):
    """A write against a store that is not ACTIVE (403)."""


class MerchantStore(Protocol):
    async def find_access(
        self, store_id: str, firebase_uid: str
    ) -> MerchantAccess | None: ...


class MerchantService:
    def __init__(self, store: MerchantStore, session: AsyncSession) -> None:
        self._store = store
        self._session = session

    async def authorize(
        self,
        store_id: str,
        firebase_uid: str,
        roles: frozenset[MembershipRole],
        *,
        write: bool,
    ) -> MerchantAccess:
        access = await self._store.find_access(store_id, firebase_uid)
        # End the read transaction: later work gets a fresh one, and no connection is
        # held across it (same rule as OrgBillingService.authorize). Run this
        # dependency before anything stages writes on the request session.
        await self._session.rollback()
        if access is None or access.store.status is StoreStatus.ARCHIVED:
            raise StoreNotFound
        if access.role not in roles:
            raise MerchantForbidden
        if write and access.store.status not in WRITABLE_STATUSES:
            raise StoreSuspended
        return access
