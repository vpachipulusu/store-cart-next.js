"""In-memory doubles for the admin users store, Firebase accounts and audit recorder."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from app.core.firebase import IdentityUserNotFound
from app.core.permissions import AdminContext
from app.repositories.admin_users import AdminUserPage, AdminUserRecord

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def user(
    user_id: str,
    *,
    role: str | None = None,
    permissions: Any = None,
    email: str | None = None,
) -> AdminUserRecord:
    return AdminUserRecord(
        id=user_id,
        firebase_uid=f"uid-{user_id}",
        email=email or f"{user_id}@example.com",
        email_verified=True,
        display_name=user_id.title(),
        bio=None,
        avatar_url=None,
        location=None,
        website=None,
        phone_number=None,
        two_factor_enabled=False,
        created_at=NOW,
        last_login_at=None,
        admin_role=role,
        admin_permissions=permissions,
    )


class FakeStore:
    def __init__(self, *users: AdminUserRecord) -> None:
        self.users = {u.id: u for u in users}
        self.locked: list[str] = []
        self.owners: set[str] = set()
        self.list_calls: list[tuple[str | None, int, int]] = []

    async def list_users(
        self, search: str | None, limit: int, offset: int
    ) -> AdminUserPage:
        self.list_calls.append((search, limit, offset))
        rows = [u for u in self.users.values() if not search or search in u.email]
        return AdminUserPage(rows[offset : offset + limit], len(rows))

    async def get_user(
        self, user_id: str, *, lock: bool = False
    ) -> AdminUserRecord | None:
        if lock:
            self.locked.append(user_id)
        return self.users.get(user_id)

    async def update_user(self, user_id: str, changes: dict[str, str | None]) -> None:
        self.users[user_id] = replace(self.users[user_id], **changes)

    async def has_owner_membership(self, user_id: str) -> bool:
        return user_id in self.owners

    async def delete_user(self, user_id: str) -> None:
        del self.users[user_id]

    async def lock_super_admin_count(self) -> int:
        return sum(1 for u in self.users.values() if u.admin_role == "super_admin")

    async def upsert_admin(
        self, user_id: str, role: str, permissions: list[str]
    ) -> None:
        self.users[user_id] = replace(
            self.users[user_id], admin_role=role, admin_permissions=permissions
        )

    async def delete_admin(self, user_id: str) -> None:
        self.users[user_id] = replace(
            self.users[user_id], admin_role=None, admin_permissions=None
        )


class FakeAccounts:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool | None]] = []
        self.missing = False
        self.failure: Exception | None = None

    async def set_user_disabled(self, uid: str, disabled: bool) -> None:
        self.calls.append(("disable", uid, disabled))
        if self.failure:
            raise self.failure
        if self.missing:
            raise IdentityUserNotFound()

    async def revoke_refresh_tokens(self, uid: str) -> None:
        self.calls.append(("revoke", uid, None))

    async def delete_user(self, uid: str) -> None:
        self.calls.append(("delete", uid, None))


class FakeAuditor:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def record(self, admin: AdminContext, **fields: Any) -> None:
        self.rows.append({"actor": admin.user_id, **fields})


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1
