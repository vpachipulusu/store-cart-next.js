"""Organisation and store persistence for the KAN-59 APIs.

Inserts use ``ON CONFLICT (slug) DO NOTHING`` so two requests racing for one slug end
with exactly one row and a clean "taken" answer instead of an exception. Row locks
(``FOR UPDATE``) serialise writes on one organisation or store.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.plans import effective_plan_key
from app.models.platform.membership import Membership, MembershipRole
from app.models.platform.organization import Organization
from app.models.platform.store import Store, StoreStatus
from app.models.platform.user import User
from app.repositories.base import BaseRepository


@dataclass(frozen=True)
class OrganizationRecord:
    id: str
    name: str
    slug: str
    subscription_tier: str
    effective_plan: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoreRecord:
    id: str
    organization_id: str
    name: str
    slug: str
    status: StoreStatus
    created_at: datetime
    updated_at: datetime


def _org(row: Organization) -> OrganizationRecord:
    return OrganizationRecord(
        row.id,
        row.name,
        row.slug,
        row.subscription_tier,
        # The plan in force: the Stripe tier or a higher, unexpired admin grant (KAN-48).
        effective_plan_key(
            row.subscription_tier,
            row.granted_plan,
            row.granted_until,
            datetime.now(UTC),
        ).value,
        row.created_at,
        row.updated_at,
    )


def _store(row: Store) -> StoreRecord:
    return StoreRecord(
        row.id,
        row.organization_id,
        row.name,
        row.slug,
        row.status,
        row.created_at,
        row.updated_at,
    )


class OrganizationsRepository(BaseRepository):
    async def get_role(
        self, organization_id: str, user_id: str
    ) -> MembershipRole | None:
        return (
            await self._session.execute(
                select(Membership.role).where(
                    Membership.organization_id == organization_id,
                    Membership.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

    async def get_organization(
        self, organization_id: str, *, lock: bool = False
    ) -> OrganizationRecord | None:
        query = select(Organization).where(Organization.id == organization_id)
        if lock:
            query = query.with_for_update()
        row = (await self._session.execute(query)).scalar_one_or_none()
        return _org(row) if row else None

    async def list_for_user(
        self, user_id: str, limit: int, offset: int
    ) -> tuple[list[tuple[OrganizationRecord, MembershipRole]], int]:
        total = (
            await self._session.execute(
                select(func.count())
                .select_from(Membership)
                .where(Membership.user_id == user_id)
            )
        ).scalar_one()
        rows = (
            await self._session.execute(
                select(Organization, Membership.role)
                .join(Membership, Membership.organization_id == Organization.id)
                .where(Membership.user_id == user_id)
                .order_by(Organization.created_at, Organization.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return [(_org(org), role) for org, role in rows], total

    async def lock_user(self, user_id: str) -> None:
        await self._session.execute(
            select(User.id).where(User.id == user_id).with_for_update()
        )

    async def count_owned(self, user_id: str) -> int:
        return (
            await self._session.execute(
                select(func.count())
                .select_from(Membership)
                .where(
                    Membership.user_id == user_id,
                    Membership.role == MembershipRole.OWNER,
                )
            )
        ).scalar_one()

    async def insert_organization(
        self, name: str, slug: str
    ) -> OrganizationRecord | None:
        """Insert, or return None when the slug is taken (also under a race)."""
        row = (
            await self._session.execute(
                insert(Organization)
                .values(name=name, slug=slug)
                .on_conflict_do_nothing(index_elements=["slug"])
                .returning(Organization)
            )
        ).scalar_one_or_none()
        return _org(row) if row else None

    async def add_membership(
        self, organization_id: str, user_id: str, role: MembershipRole
    ) -> None:
        self._session.add(
            Membership(organization_id=organization_id, user_id=user_id, role=role)
        )
        await self._session.flush()

    async def update_organization(
        self, organization_id: str, values: dict[str, Any]
    ) -> OrganizationRecord:
        row = (
            await self._session.execute(
                update(Organization)
                .where(Organization.id == organization_id)
                .values(**values)
                .returning(Organization)
            )
        ).scalar_one()
        return _org(row)

    async def stores_for(
        self, organization_ids: list[str], per_organization: int
    ) -> dict[str, list[StoreRecord]]:
        """Visible (non-archived) stores, at most ``per_organization`` each."""
        if not organization_ids:
            return {}
        rank = (
            func.row_number()
            .over(
                partition_by=Store.organization_id,
                order_by=(Store.created_at, Store.id),
            )
            .label("rank")
        )
        ranked = (
            select(Store.id.label("store_id"), rank)
            .where(
                Store.organization_id.in_(organization_ids),
                Store.status != StoreStatus.ARCHIVED,
            )
            .subquery()
        )
        rows = (
            await self._session.execute(
                select(Store)
                .join(ranked, ranked.c.store_id == Store.id)
                .where(ranked.c.rank <= per_organization)
                .order_by(Store.organization_id, Store.created_at, Store.id)
            )
        ).scalars()
        grouped: dict[str, list[StoreRecord]] = {}
        for row in rows:
            grouped.setdefault(row.organization_id, []).append(_store(row))
        return grouped

    async def list_stores(
        self, organization_id: str, limit: int, offset: int
    ) -> tuple[list[StoreRecord], int]:
        visible = (
            Store.organization_id == organization_id,
            Store.status != StoreStatus.ARCHIVED,
        )
        total = (
            await self._session.execute(
                select(func.count()).select_from(Store).where(*visible)
            )
        ).scalar_one()
        rows = (
            await self._session.execute(
                select(Store)
                .where(*visible)
                .order_by(Store.created_at, Store.id)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return [_store(row) for row in rows], total

    async def count_stores(self, organization_id: str) -> int:
        """Stores that count against the plan limit (not archived, not FAILED)."""
        return (
            await self._session.execute(
                select(func.count())
                .select_from(Store)
                .where(
                    Store.organization_id == organization_id,
                    Store.status.not_in((StoreStatus.ARCHIVED, StoreStatus.FAILED)),
                )
            )
        ).scalar_one()

    async def insert_store(
        self, organization_id: str, name: str, slug: str
    ) -> StoreRecord | None:
        """Insert a PROVISIONING store, or return None when the slug is taken."""
        row = (
            await self._session.execute(
                insert(Store)
                .values(
                    organization_id=organization_id,
                    name=name,
                    slug=slug,
                    status=StoreStatus.PROVISIONING,
                )
                .on_conflict_do_nothing(index_elements=["slug"])
                .returning(Store)
            )
        ).scalar_one_or_none()
        return _store(row) if row else None

    async def get_store(
        self, store_id: str, *, lock: bool = False
    ) -> StoreRecord | None:
        query = select(Store).where(Store.id == store_id)
        if lock:
            query = query.with_for_update()
        row = (await self._session.execute(query)).scalar_one_or_none()
        return _store(row) if row else None

    async def update_store(self, store_id: str, values: dict[str, Any]) -> StoreRecord:
        row = (
            await self._session.execute(
                update(Store)
                .where(Store.id == store_id)
                .values(**values)
                .returning(Store)
            )
        ).scalar_one()
        return _store(row)
