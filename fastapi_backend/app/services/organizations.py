"""Organisations and stores (KAN-59): create, list, read and update.

Authorisation always comes from the ``memberships`` table, read inside the same
transaction as the write and under a row lock, so a membership revoked a moment ago
cannot be used. Nothing about organisation, owner or role is taken from a request body.

Role rules:

* any member reads their organisations and their (non-archived) stores;
* OWNER and ADMIN create stores and change names;
* only OWNER changes a slug (a slug is the public identity of an organisation or store);
* creating an organisation makes the caller its OWNER in the same transaction.

A caller who is not a member of an organisation gets ``OrganizationNotFound`` whether
or not it exists. Every sensitive change writes an ``audit_logs`` row in the caller's
transaction, so the change and its audit entry commit or roll back together.
"""

import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import PLANS, PlanKey
from app.core.slugs import normalize_slug
from app.models.platform.membership import MembershipRole
from app.models.platform.store import StoreStatus
from app.repositories.audit import AuditRepository
from app.repositories.merchant import MerchantAccess
from app.repositories.organizations import (
    OrganizationRecord,
    OrganizationsRepository,
    StoreRecord,
)
from app.services.audit import sanitize

MANAGE_ROLES = frozenset({MembershipRole.OWNER, MembershipRole.ADMIN})
SLUG_ROLES = frozenset({MembershipRole.OWNER})
MAX_NAME_LENGTH = 100
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50
# Stores shown inline under an organisation; more are fetched from the stores list.
MAX_INLINE_STORES = 100
# Abuse guard: organisations one user may own.
MAX_OWNED_ORGANIZATIONS = 10


# Control, format (bidi), line/paragraph separators, surrogates, private use, unassigned.
FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Cs", "Co", "Cn"})
# Letters that render as blank (Hangul fillers, braille blank).
INVISIBLE_CHARS = frozenset("ㅤ⠀ﾠᅟᅠ")


class OrganizationNotFound(Exception):
    """No such organisation, or the caller is not a member (404)."""


class StoreNotFound(Exception):
    """No such store, or one the caller cannot see (404)."""


class OrgForbidden(Exception):
    """A member whose role may not do this (403)."""


class StoreNotActive(Exception):
    """A change to a store that is not ACTIVE (403)."""


class SlugTaken(Exception):
    """The slug is already used (409)."""


class StoreLimitReached(Exception):
    """The organisation's plan allows no more stores (409)."""


class OrganizationLimitReached(Exception):
    """The caller already owns the maximum number of organisations (409)."""


class InvalidName(ValueError):
    """The name is empty, too long or has control characters (422)."""


def normalize_name(raw: str) -> str:
    name = unicodedata.normalize("NFC", raw).strip()
    if not name or len(name) > MAX_NAME_LENGTH:
        raise InvalidName
    if any(unicodedata.category(char) in FORBIDDEN_CATEGORIES for char in name):
        raise InvalidName
    if all(char in INVISIBLE_CHARS or char.isspace() for char in name):
        raise InvalidName
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidName from None
    return name


def _slug_conflict(exc: IntegrityError) -> Exception:
    """SlugTaken for a unique violation; anything else is a bug and stays an error."""
    orig = exc.orig
    state = getattr(orig, "sqlstate", None) or getattr(
        getattr(orig, "__cause__", None), "sqlstate", None
    )
    return SlugTaken() if state == "23505" else exc


@dataclass(frozen=True)
class OrganizationView:
    organization: OrganizationRecord
    role: MembershipRole
    stores: list[StoreRecord]
    stores_truncated: bool


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    total: int
    limit: int
    offset: int


class OrganizationsService:
    def __init__(self, store: OrganizationsRepository, session: AsyncSession) -> None:
        self._store = store
        self._session = session
        self._audit = AuditRepository(session)

    # Reads -----------------------------------------------------------------

    async def list_organizations(
        self, user_id: str, limit: int, offset: int
    ) -> Page[OrganizationView]:
        """Only the caller's own organisations, each with their role and stores."""
        rows, total = await self._store.list_for_user(user_id, limit, offset)
        stores = await self._store.stores_for(
            [org.id for org, _ in rows], MAX_INLINE_STORES + 1
        )
        views = [self._view(org, role, stores.get(org.id, [])) for org, role in rows]
        await self._session.rollback()
        return Page(views, total, limit, offset)

    async def get_organization(
        self, organization_id: str, user_id: str
    ) -> OrganizationView:
        role = await self._store.get_role(organization_id, user_id)
        organization = await self._store.get_organization(organization_id)
        if role is None or organization is None:
            raise OrganizationNotFound
        stores = await self._store.stores_for([organization_id], MAX_INLINE_STORES + 1)
        view = self._view(organization, role, stores.get(organization_id, []))
        await self._session.rollback()
        return view

    async def list_stores(
        self, organization_id: str, user_id: str, limit: int, offset: int
    ) -> Page[StoreRecord]:
        if await self._store.get_role(organization_id, user_id) is None:
            raise OrganizationNotFound
        items, total = await self._store.list_stores(organization_id, limit, offset)
        await self._session.rollback()
        return Page(items, total, limit, offset)

    async def get_store(self, store_id: str) -> StoreRecord:
        """Read a store the caller was already authorised for (``require_merchant``)."""
        store = await self._store.get_store(store_id)
        await self._session.rollback()
        if store is None or store.status is StoreStatus.ARCHIVED:
            raise StoreNotFound
        return store

    # Organisation writes ---------------------------------------------------

    async def create_organization(
        self, user_id: str, *, name: str, slug: str, request_id: str | None
    ) -> OrganizationView:
        clean_name = normalize_name(name)
        clean_slug = normalize_slug(slug)
        # Lock the caller's user row so parallel creates cannot all pass the cap.
        await self._store.lock_user(user_id)
        if await self._store.count_owned(user_id) >= MAX_OWNED_ORGANIZATIONS:
            raise OrganizationLimitReached
        organization = await self._store.insert_organization(clean_name, clean_slug)
        if organization is None:
            raise SlugTaken
        await self._store.add_membership(organization.id, user_id, MembershipRole.OWNER)
        await self._record(
            user_id,
            "org.create",
            "organization",
            organization.id,
            organization.id,
            after={
                "name": organization.name,
                "slug": organization.slug,
                "role": MembershipRole.OWNER,
            },
            request_id=request_id,
        )
        await self._session.commit()
        return self._view(organization, MembershipRole.OWNER, [])

    async def update_organization(
        self,
        organization_id: str,
        user_id: str,
        *,
        name: str | None,
        slug: str | None,
        request_id: str | None,
    ) -> OrganizationView:
        # Membership first (no lock), so a non-member can neither learn the
        # organisation exists nor hold its row lock; then lock and re-read the role.
        await self._require_member(organization_id, user_id, MANAGE_ROLES)
        current = await self._store.get_organization(organization_id, lock=True)
        role = await self._store.get_role(organization_id, user_id)
        if current is None or role is None:
            raise OrganizationNotFound
        values = self._changes(current.name, current.slug, name, slug, role)
        if values:
            try:
                updated = await self._store.update_organization(current.id, values)
            except IntegrityError as exc:
                await self._session.rollback()
                raise _slug_conflict(exc) from None
            await self._record(
                user_id,
                "org.update",
                "organization",
                current.id,
                current.id,
                before={"name": current.name, "slug": current.slug},
                after={"name": updated.name, "slug": updated.slug},
                request_id=request_id,
            )
            await self._session.commit()
            current = updated
        else:
            await self._session.rollback()
        stores = await self._store.stores_for([current.id], MAX_INLINE_STORES + 1)
        view = self._view(current, role, stores.get(current.id, []))
        await self._session.rollback()
        return view

    # Store writes ----------------------------------------------------------

    async def create_store(
        self,
        organization_id: str,
        user_id: str,
        *,
        name: str,
        slug: str,
        request_id: str | None,
    ) -> StoreRecord:
        # The organisation row lock serialises concurrent creates, so the plan
        # limit below cannot be overshot by two requests counting at once.
        await self._require_member(organization_id, user_id, MANAGE_ROLES)
        organization = await self._store.get_organization(organization_id, lock=True)
        role = await self._store.get_role(organization_id, user_id)
        if organization is None or role is None:
            raise OrganizationNotFound
        if role not in MANAGE_ROLES:
            raise OrgForbidden
        clean_name = normalize_name(name)
        clean_slug = normalize_slug(slug)
        limit = self._max_stores(organization.subscription_tier)
        if (
            limit is not None
            and await self._store.count_stores(organization_id) >= limit
        ):
            raise StoreLimitReached
        store = await self._store.insert_store(organization_id, clean_name, clean_slug)
        if store is None:
            raise SlugTaken
        await self._record(
            user_id,
            "store.create",
            "store",
            store.id,
            organization_id,
            store_id=store.id,
            after={"name": store.name, "slug": store.slug, "status": store.status},
            request_id=request_id,
        )
        await self._session.commit()
        return store

    async def update_store(
        self,
        access: MerchantAccess,
        *,
        name: str | None,
        slug: str | None,
        request_id: str | None,
    ) -> StoreRecord:
        """Update a store; ``access`` came from ``require_merchant`` and is rechecked."""
        current = await self._store.get_store(access.store.id, lock=True)
        if current is None or current.status is StoreStatus.ARCHIVED:
            raise StoreNotFound
        role = await self._store.get_role(current.organization_id, access.user_id)
        if role is None:
            raise StoreNotFound
        if role not in MANAGE_ROLES:
            raise OrgForbidden
        if current.status is not StoreStatus.ACTIVE:
            raise StoreNotActive
        values = self._changes(current.name, current.slug, name, slug, role)
        if not values:
            await self._session.rollback()
            return current
        try:
            updated = await self._store.update_store(current.id, values)
        except IntegrityError as exc:
            await self._session.rollback()
            raise _slug_conflict(exc) from None
        await self._record(
            access.user_id,
            "store.update",
            "store",
            current.id,
            current.organization_id,
            store_id=current.id,
            before={"name": current.name, "slug": current.slug},
            after={"name": updated.name, "slug": updated.slug},
            request_id=request_id,
        )
        await self._session.commit()
        return updated

    # Helpers ---------------------------------------------------------------

    async def _require_member(
        self,
        organization_id: str,
        user_id: str,
        roles: frozenset[MembershipRole],
    ) -> None:
        """Unlocked membership check: 404 for a non-member, 403 for a low role."""
        role = await self._store.get_role(organization_id, user_id)
        if role is None:
            raise OrganizationNotFound
        if role not in roles:
            raise OrgForbidden

    @staticmethod
    def _view(
        organization: OrganizationRecord,
        role: MembershipRole,
        stores: list[StoreRecord],
    ) -> OrganizationView:
        return OrganizationView(
            organization,
            role,
            stores[:MAX_INLINE_STORES],
            len(stores) > MAX_INLINE_STORES,
        )

    @staticmethod
    def _max_stores(tier: str) -> int | None:
        try:
            return PLANS[PlanKey(tier)].max_stores
        except ValueError:
            return PLANS[PlanKey.FREE].max_stores

    @staticmethod
    def _changes(
        current_name: str,
        current_slug: str,
        name: str | None,
        slug: str | None,
        role: MembershipRole,
    ) -> dict[str, Any]:
        """Validated column changes the role may make; unchanged values are dropped."""
        if role not in MANAGE_ROLES:
            raise OrgForbidden
        values: dict[str, Any] = {}
        if name is not None:
            clean_name = normalize_name(name)
            if clean_name != current_name:
                values["name"] = clean_name
        if slug is not None:
            if role not in SLUG_ROLES:
                raise OrgForbidden
            clean_slug = normalize_slug(slug)
            if clean_slug != current_slug:
                values["slug"] = clean_slug
        return values

    async def _record(
        self,
        user_id: str,
        action: str,
        resource: str,
        resource_id: str,
        organization_id: str,
        *,
        store_id: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        request_id: str | None,
    ) -> None:
        metadata: dict[str, Any] = {}
        for key, value in (
            ("request_id", request_id),
            ("before", before),
            ("after", after),
        ):
            if value is not None:
                metadata[key] = sanitize(value)
        await self._audit.add(
            user_id=user_id,
            organization_id=organization_id,
            store_id=store_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            metadata=metadata,
            ip_address=None,
            user_agent=None,
        )
