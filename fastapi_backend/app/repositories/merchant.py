from dataclasses import dataclass

from sqlalchemy import select

from app.models.platform.membership import Membership, MembershipRole
from app.models.platform.organization import Organization
from app.models.platform.store import Store, StoreStatus
from app.models.platform.user import User
from app.repositories.base import BaseRepository


@dataclass(frozen=True)
class OrganizationRef:
    id: str
    name: str
    slug: str


@dataclass(frozen=True)
class StoreRef:
    id: str
    organization_id: str
    name: str
    slug: str
    status: StoreStatus


@dataclass(frozen=True)
class MerchantAccess:
    """One caller's standing on one store: who they are, the store and their role."""

    user_id: str
    organization: OrganizationRef
    store: StoreRef
    role: MembershipRole


class MerchantRepository(BaseRepository):
    async def find_access(
        self, store_id: str, firebase_uid: str
    ) -> MerchantAccess | None:
        """The caller's membership of the organisation that owns the store.

        One statement joins user, membership, store and organisation, so "no such
        store", "not your store" and "no such user" are the same single query that
        returns no row: nothing distinguishes them in result or cost.
        """
        row = (
            await self._session.execute(
                select(User.id, Organization, Store, Membership.role)
                .select_from(User)
                .join(Membership, Membership.user_id == User.id)
                .join(Organization, Organization.id == Membership.organization_id)
                .join(Store, Store.organization_id == Organization.id)
                .where(User.firebase_uid == firebase_uid, Store.id == store_id)
            )
        ).first()
        if row is None:
            return None
        user_id, organization, store, role = row
        return MerchantAccess(
            user_id,
            OrganizationRef(organization.id, organization.name, organization.slug),
            StoreRef(
                store.id, store.organization_id, store.name, store.slug, store.status
            ),
            role,
        )
