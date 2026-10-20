"""Public storefront read (KAN-65): the only unauthenticated read across tenants.

It selects the public columns and nothing else, and only for ACTIVE stores. The filter
is an allowlist (``status == ACTIVE``): any other status, now or added later, is invisible.
"""

from dataclasses import dataclass

from sqlalchemy import func, select

from app.models.platform.store import Store, StoreStatus
from app.repositories.base import BaseRepository


@dataclass(frozen=True)
class PublicStore:
    name: str
    slug: str


class StorefrontRepository(BaseRepository):
    async def find_active_by_slug(self, slug: str) -> PublicStore | None:
        row = (
            await self._session.execute(
                select(Store.name, Store.slug).where(
                    Store.slug == slug, Store.status == StoreStatus.ACTIVE
                )
            )
        ).one_or_none()
        return PublicStore(name=row.name, slug=row.slug) if row else None

    async def find_active_id_by_slug(self, slug: str) -> str | None:
        """The id of the ACTIVE store with this slug (internal use: opening its database)."""
        row = (
            await self._session.execute(
                select(Store.id).where(
                    Store.slug == slug, Store.status == StoreStatus.ACTIVE
                )
            )
        ).one_or_none()
        return str(row.id) if row else None

    async def sample_active_store_ids(self, limit: int) -> list[str]:
        """Up to ``limit`` ACTIVE stores that have a database, in random order (scheduled jobs)."""
        rows = await self._session.execute(
            select(Store.id)
            .where(
                Store.status == StoreStatus.ACTIVE,
                Store.connection_string_encrypted.is_not(None),
            )
            .order_by(func.random())
            .limit(limit)
        )
        return [str(store_id) for store_id in rows.scalars()]
