"""Admin user management (KAN-47) and the privilege-escalation guards (KAN-124).

Every state change locks the target user row, stages its audit row in the same
transaction and commits once after ``record`` (see ``app.services.audit``). A refusal
raises before any commit, so the request-scoped session rolls back.

Rules, enforced here and not only in the router:

* Nobody may change their own admin role, ban or delete themselves, or revoke
  themselves.
* ``assert_can_grant`` decides grants: only a super admin grants ``super_admin`` or
  ``*``, and nobody grants a permission they do not hold.
* An admin who is not a super admin may not manage a super admin, nor an admin
  holding permissions they lack.
* The last super admin can neither be revoked nor demoted.
"""

from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firebase import IdentityUserNotFound
from app.core.permissions import (
    ROLE_SUPER_ADMIN,
    AdminContext,
    assert_can_grant,
    effective_permissions,
)
from app.repositories.admin_users import AdminUserPage, AdminUserRecord
from app.services.me import OwnershipConflict, UserNotFound

__all__ = [
    "AdminActionConflict",
    "AdminActionForbidden",
    "AdminUsersService",
    "OwnershipConflict",
    "UserNotFound",
]

UPDATABLE_FIELDS = frozenset(
    {"display_name", "bio", "location", "website", "phone_number", "avatar_url"}
)
MAX_PAGE_SIZE = 100


class AdminActionForbidden(Exception):
    """The caller lacks the standing for this change (403)."""


class AdminActionConflict(Exception):
    """The change is refused because of the current state (409)."""


class UsersStore(Protocol):
    async def list_users(
        self, search: str | None, limit: int, offset: int
    ) -> AdminUserPage: ...
    async def get_user(
        self, user_id: str, *, lock: bool = False
    ) -> AdminUserRecord | None: ...
    async def update_user(
        self, user_id: str, changes: dict[str, str | None]
    ) -> None: ...
    async def has_owner_membership(self, user_id: str) -> bool: ...
    async def delete_user(self, user_id: str) -> None: ...
    async def lock_super_admin_count(self) -> int: ...
    async def upsert_admin(
        self, user_id: str, role: str, permissions: list[str]
    ) -> None: ...
    async def delete_admin(self, user_id: str) -> None: ...


class UserAccounts(Protocol):
    async def set_user_disabled(self, uid: str, disabled: bool) -> None: ...
    async def revoke_refresh_tokens(self, uid: str) -> None: ...
    async def delete_user(self, uid: str) -> None: ...


class AuditRecorder(Protocol):
    async def record(
        self,
        admin: AdminContext,
        *,
        action: str,
        resource: str,
        resource_id: str | None = None,
        organization_id: str | None = None,
        before: object = None,
        after: object = None,
        details: object = None,
    ) -> None: ...


def _admin_state(user: AdminUserRecord) -> dict[str, Any] | None:
    if user.admin_role is None:
        return None
    held = effective_permissions(user.admin_role, user.admin_permissions)
    return {"role": user.admin_role, "permissions": sorted(held)}


class AdminUsersService:
    def __init__(
        self,
        store: UsersStore,
        session: AsyncSession,
        accounts: UserAccounts,
        auditor: AuditRecorder,
    ) -> None:
        self.store, self.session = store, session
        self.accounts, self.auditor = accounts, auditor

    async def list_users(
        self, search: str | None, limit: int, offset: int
    ) -> AdminUserPage:
        return await self.store.list_users(
            search, min(max(limit, 1), MAX_PAGE_SIZE), max(offset, 0)
        )

    async def get_user(self, user_id: str) -> AdminUserRecord:
        user = await self.store.get_user(user_id)
        if user is None:
            raise UserNotFound()
        return user

    async def update_user(
        self, actor: AdminContext, user_id: str, changes: Mapping[str, str | None]
    ) -> AdminUserRecord:
        if not changes or not changes.keys() <= UPDATABLE_FIELDS:
            raise ValueError("Invalid user fields")
        target = await self._locked_target(user_id)
        self._assert_can_manage(actor, target)
        await self.store.update_user(user_id, dict(changes))
        await self.auditor.record(
            actor,
            action="admin.users.update",
            resource="users",
            resource_id=user_id,
            details={"fields": sorted(changes)},  # names only: values can be PII
        )
        await self.session.commit()
        updated = await self.store.get_user(user_id)
        if updated is None:  # pragma: no cover - the row was just updated
            raise UserNotFound()
        return updated

    async def delete_user(self, actor: AdminContext, user_id: str) -> None:
        self._refuse_self(actor, user_id)
        target = await self._locked_target(user_id)
        if target.admin_role is not None:
            raise AdminActionConflict()  # revoke the admin grant first
        if await self.store.has_owner_membership(user_id):
            raise OwnershipConflict()
        await self.store.delete_user(user_id)
        await self.auditor.record(
            actor, action="admin.users.delete", resource="users", resource_id=user_id
        )
        # Firebase cannot join the SQL transaction: delete it last, then commit. A SQL
        # failure on commit leaves a Firebase-less row for an operator (backend-profile.md).
        await self.accounts.delete_user(target.firebase_uid)
        await self.session.commit()

    async def set_banned(
        self,
        actor: AdminContext,
        user_id: str,
        banned: bool,
        reason: str | None = None,
    ) -> None:
        self._refuse_self(actor, user_id)
        target = await self._locked_target(user_id)
        self._assert_can_manage(actor, target)
        await self.auditor.record(
            actor,
            action="admin.users.ban" if banned else "admin.users.unban",
            resource="users",
            resource_id=user_id,
            details={"reason": reason} if reason else None,
        )
        try:
            await self.accounts.set_user_disabled(target.firebase_uid, banned)
            if banned:
                await self.accounts.revoke_refresh_tokens(target.firebase_uid)
        except IdentityUserNotFound:
            raise UserNotFound() from None
        await self.session.commit()

    async def grant_admin(
        self,
        actor: AdminContext,
        user_id: str,
        role: str,
        permissions: list[str],
    ) -> dict[str, Any]:
        if not assert_can_grant(actor, role, permissions):
            raise AdminActionForbidden()
        # KAN-124: an admin never writes their own role or permissions, up or down.
        if user_id == actor.user_id:
            raise AdminActionForbidden()
        target = await self._locked_target(user_id)
        self._assert_can_manage(actor, target)
        if target.admin_role == ROLE_SUPER_ADMIN and role != ROLE_SUPER_ADMIN:
            await self._assert_not_last_super_admin()
        stored = sorted(set(permissions))
        before = _admin_state(target)
        await self.store.upsert_admin(user_id, role, stored)
        after = {"role": role, "permissions": stored}
        await self.auditor.record(
            actor,
            action="admin.users.grant_admin",
            resource="admin_users",
            resource_id=user_id,
            before=before,
            after=after,
        )
        await self.session.commit()
        return after

    async def revoke_admin(self, actor: AdminContext, user_id: str) -> None:
        self._refuse_self(actor, user_id)
        target = await self._locked_target(user_id)
        if target.admin_role is None:
            raise UserNotFound()
        self._assert_can_manage(actor, target)
        if target.admin_role == ROLE_SUPER_ADMIN:
            await self._assert_not_last_super_admin()
        await self.store.delete_admin(user_id)
        await self.auditor.record(
            actor,
            action="admin.users.revoke_admin",
            resource="admin_users",
            resource_id=user_id,
            before=_admin_state(target),
        )
        await self.session.commit()

    async def _locked_target(self, user_id: str) -> AdminUserRecord:
        target = await self.store.get_user(user_id, lock=True)
        if target is None:
            raise UserNotFound()
        return target

    @staticmethod
    def _refuse_self(actor: AdminContext, user_id: str) -> None:
        if user_id == actor.user_id:
            raise AdminActionConflict()

    @staticmethod
    def _assert_can_manage(actor: AdminContext, target: AdminUserRecord) -> None:
        if target.admin_role is None or actor.role == ROLE_SUPER_ADMIN:
            return
        held = effective_permissions(target.admin_role, target.admin_permissions)
        if target.admin_role == ROLE_SUPER_ADMIN or not held <= actor.permissions:
            raise AdminActionForbidden()

    async def _assert_not_last_super_admin(self) -> None:
        if await self.store.lock_super_admin_count() <= 1:
            raise AdminActionConflict()
