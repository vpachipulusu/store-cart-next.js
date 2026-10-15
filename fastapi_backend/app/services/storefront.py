"""Public storefront lookup (KAN-65)."""

from typing import Protocol

from app.core.slugs import InvalidSlug, ReservedSlug, normalize_slug
from app.repositories.storefront import PublicStore


class StorefrontReader(Protocol):
    async def find_active_by_slug(self, slug: str) -> PublicStore | None: ...


class StorefrontService:
    def __init__(self, repository: StorefrontReader) -> None:
        self._repository = repository

    async def lookup(self, raw_slug: str) -> PublicStore | None:
        """The ACTIVE store with this slug, else None.

        A malformed or reserved slug cannot name a store, so it answers None without
        touching the database; callers cannot tell it from an unknown store.
        """
        try:
            slug = normalize_slug(raw_slug)
        except (InvalidSlug, ReservedSlug):
            return None
        return await self._repository.find_active_by_slug(slug)
