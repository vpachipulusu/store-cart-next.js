import pytest

from app.core.firebase import IdentityProviderUnavailable
from app.core.permissions import ADMIN_PERMISSIONS, AdminContext
from app.services.admin_users import (
    MAX_PAGE_SIZE,
    AdminActionConflict,
    AdminActionForbidden,
    AdminUsersService,
    OwnershipConflict,
    UserNotFound,
)
from tests.fakes_admin_users import (
    FakeAccounts,
    FakeAuditor,
    FakeSession,
    FakeStore,
    user,
)

SUPER = AdminContext("sa", "super_admin", ADMIN_PERMISSIONS)
MANAGER_PERMISSIONS = frozenset(
    {"users.read", "users.update", "users.delete", "admins.create", "admins.delete"}
)
MANAGER = AdminContext("mgr", "admin", MANAGER_PERMISSIONS)


def build(*users):
    store, accounts, auditor, session = (
        FakeStore(*users),
        FakeAccounts(),
        FakeAuditor(),
        FakeSession(),
    )
    service = AdminUsersService(store, session, accounts, auditor)
    return service, store, accounts, auditor, session


def people():
    return (
        user("sa", role="super_admin", permissions=["*"]),
        user("sa2", role="super_admin", permissions=["*"]),
        user("mgr", role="admin", permissions=sorted(MANAGER_PERMISSIONS)),
        user("peer", role="admin", permissions=["users.read"]),
        user("big", role="admin", permissions=["settings.write", "users.read"]),
        user("bob"),
    )


async def test_list_caps_the_page_size_and_floors_the_offset():
    service, store, *_ = build(*people())

    await service.list_users(None, 10_000, -5)

    assert store.list_calls == [(None, MAX_PAGE_SIZE, 0)]


async def test_get_user_missing_raises_not_found():
    service, *_ = build()
    with pytest.raises(UserNotFound):
        await service.get_user("nobody")


async def test_update_writes_audit_with_field_names_only_and_commits_once():
    service, store, _, auditor, session = build(*people())

    updated = await service.update_user(MANAGER, "bob", {"bio": "secret bio"})

    assert updated.bio == "secret bio"
    assert session.commits == 1
    (row,) = auditor.rows
    assert row["action"] == "admin.users.update"
    assert row["details"] == {"fields": ["bio"]}
    assert "secret bio" not in repr(row)
    assert store.locked == ["bob"]


@pytest.mark.parametrize("changes", [{}, {"email": "x@example.com"}, {"role": "x"}])
async def test_update_rejects_empty_or_unknown_fields(changes):
    service, *_ = build(*people())
    with pytest.raises(ValueError):
        await service.update_user(MANAGER, "bob", changes)


async def test_update_of_a_missing_user_is_not_found():
    service, *_ = build(*people())
    with pytest.raises(UserNotFound):
        await service.update_user(MANAGER, "ghost", {"bio": "x"})


async def test_delete_removes_the_user_firebase_account_and_audits():
    service, store, accounts, auditor, session = build(*people())

    await service.delete_user(MANAGER, "bob")

    assert "bob" not in store.users
    assert accounts.calls == [("delete", "uid-bob", None)]
    assert [r["action"] for r in auditor.rows] == ["admin.users.delete"]
    assert session.commits == 1


async def test_delete_refuses_self_admins_and_organisation_owners():
    service, store, accounts, auditor, session = build(*people())
    store.owners.add("bob")

    with pytest.raises(AdminActionConflict):
        await service.delete_user(MANAGER, "mgr")
    with pytest.raises(AdminActionConflict):
        await service.delete_user(SUPER, "peer")
    with pytest.raises(OwnershipConflict):
        await service.delete_user(MANAGER, "bob")

    assert accounts.calls == [] and auditor.rows == [] and session.commits == 0


async def test_ban_disables_and_revokes_tokens_then_audits_the_reason():
    service, _, accounts, auditor, session = build(*people())

    await service.set_banned(MANAGER, "bob", True, "abuse")

    assert accounts.calls == [("disable", "uid-bob", True), ("revoke", "uid-bob", None)]
    assert auditor.rows[0]["action"] == "admin.users.ban"
    assert auditor.rows[0]["details"] == {"reason": "abuse"}
    assert session.commits == 1


async def test_unban_enables_without_revoking():
    service, _, accounts, auditor, _ = build(*people())

    await service.set_banned(MANAGER, "bob", False)

    assert accounts.calls == [("disable", "uid-bob", False)]
    assert auditor.rows[0]["action"] == "admin.users.unban"
    assert auditor.rows[0]["details"] is None


async def test_ban_refuses_self_and_stronger_admins():
    service, _, accounts, _, session = build(*people())

    with pytest.raises(AdminActionConflict):
        await service.set_banned(MANAGER, "mgr", True)
    with pytest.raises(AdminActionForbidden):
        await service.set_banned(MANAGER, "sa", True)  # super admin
    with pytest.raises(AdminActionForbidden):
        await service.set_banned(MANAGER, "big", True)  # holds permissions mgr lacks

    assert accounts.calls == [] and session.commits == 0


async def test_ban_of_a_user_unknown_to_firebase_is_not_found_and_not_committed():
    service, _, accounts, _, session = build(*people())
    accounts.missing = True

    with pytest.raises(UserNotFound):
        await service.set_banned(MANAGER, "bob", True)

    assert session.commits == 0


async def test_ban_does_not_commit_when_firebase_is_down():
    service, _, accounts, _, session = build(*people())
    accounts.failure = IdentityProviderUnavailable()

    with pytest.raises(IdentityProviderUnavailable):
        await service.set_banned(MANAGER, "bob", True)

    assert session.commits == 0


async def test_super_admin_may_ban_another_super_admin():
    service, _, accounts, *_ = build(*people())

    await service.set_banned(SUPER, "sa2", True)

    assert accounts.calls[0] == ("disable", "uid-sa2", True)


async def test_grant_stores_sorted_unique_permissions_and_audits_before_and_after():
    service, store, _, auditor, session = build(*people())

    granted = await service.grant_admin(
        MANAGER, "bob", "admin", ["users.update", "users.read", "users.read"]
    )

    assert granted == {"role": "admin", "permissions": ["users.read", "users.update"]}
    assert store.users["bob"].admin_permissions == ["users.read", "users.update"]
    (row,) = auditor.rows
    assert row["action"] == "admin.users.grant_admin"
    assert row["resource_id"] == "bob" and row["before"] is None
    assert row["after"] == granted
    assert session.commits == 1


async def test_regrant_audits_the_previous_state():
    service, _, _, auditor, _ = build(*people())

    await service.grant_admin(MANAGER, "peer", "admin", ["users.update"])

    assert auditor.rows[0]["before"] == {"role": "admin", "permissions": ["users.read"]}


@pytest.mark.parametrize(
    ("role", "permissions"),
    [
        ("admin", ["settings.write"]),  # a permission the manager does not hold
        ("admin", ["*"]),  # wildcard by a non-super admin
        ("super_admin", ["*"]),  # super_admin role by a non-super admin
        ("super_admin", ["users.read"]),
        ("admin", ["not.a.permission"]),
    ],
)
async def test_non_super_admin_cannot_grant_more_than_they_hold(role, permissions):
    service, store, _, auditor, session = build(*people())

    with pytest.raises(AdminActionForbidden):
        await service.grant_admin(MANAGER, "bob", role, permissions)

    assert store.users["bob"].admin_role is None
    assert auditor.rows == [] and session.commits == 0


async def test_an_admin_cannot_grant_themselves_anything():
    service, store, _, auditor, _ = build(*people())
    before = store.users["mgr"]

    for role, permissions in [
        ("admin", ["users.read"]),
        ("admin", ["settings.write"]),
        ("super_admin", ["*"]),
    ]:
        with pytest.raises(AdminActionForbidden):
            await service.grant_admin(MANAGER, "mgr", role, permissions)

    assert store.users["mgr"] == before and auditor.rows == []


async def test_even_a_super_admin_cannot_change_their_own_grant():
    service, store, *_ = build(*people())
    before = store.users["sa"]

    with pytest.raises(AdminActionForbidden):
        await service.grant_admin(SUPER, "sa", "admin", ["users.read"])

    assert store.users["sa"] == before


async def test_super_admin_can_grant_super_admin_with_wildcard():
    service, store, *_ = build(*people())

    await service.grant_admin(SUPER, "bob", "super_admin", ["*"])

    assert store.users["bob"].admin_role == "super_admin"


async def test_grant_cannot_touch_a_super_admin_or_a_stronger_admin():
    service, store, _, auditor, _ = build(*people())

    with pytest.raises(AdminActionForbidden):
        await service.grant_admin(MANAGER, "sa", "admin", ["users.read"])
    with pytest.raises(AdminActionForbidden):
        await service.grant_admin(MANAGER, "big", "admin", ["users.read"])

    assert store.users["sa"].admin_role == "super_admin"
    assert auditor.rows == []


async def test_grant_to_a_missing_user_is_not_found():
    service, *_ = build(*people())
    with pytest.raises(UserNotFound):
        await service.grant_admin(MANAGER, "ghost", "admin", ["users.read"])


async def test_demoting_the_last_super_admin_is_refused():
    service, *_ = build(user("only", role="super_admin", permissions=["*"]))

    with pytest.raises(AdminActionConflict):
        await service.grant_admin(SUPER, "only", "admin", ["users.read"])


async def test_demoting_a_super_admin_is_allowed_when_another_remains():
    service, store, *_ = build(*people())

    await service.grant_admin(SUPER, "sa2", "admin", ["users.read"])

    assert store.users["sa2"].admin_role == "admin"


async def test_revoke_removes_the_grant_and_audits_the_previous_state():
    service, store, _, auditor, session = build(*people())

    await service.revoke_admin(MANAGER, "peer")

    assert store.users["peer"].admin_role is None
    (row,) = auditor.rows
    assert row["action"] == "admin.users.revoke_admin"
    assert row["before"] == {"role": "admin", "permissions": ["users.read"]}
    assert session.commits == 1


async def test_revoke_refuses_self_non_admins_and_stronger_targets():
    service, _, _, auditor, session = build(*people())

    with pytest.raises(AdminActionConflict):
        await service.revoke_admin(MANAGER, "mgr")
    with pytest.raises(AdminActionConflict):
        await service.revoke_admin(SUPER, "sa")
    with pytest.raises(UserNotFound):
        await service.revoke_admin(MANAGER, "bob")
    with pytest.raises(AdminActionForbidden):
        await service.revoke_admin(MANAGER, "sa2")
    with pytest.raises(AdminActionForbidden):
        await service.revoke_admin(MANAGER, "big")

    assert auditor.rows == [] and session.commits == 0


async def test_revoking_the_last_super_admin_is_refused():
    service, store, _, auditor, _ = build(
        user("only", role="super_admin", permissions=["*"]),
        user("other", role="admin", permissions=["users.read"]),
    )

    with pytest.raises(AdminActionConflict):
        await service.revoke_admin(SUPER, "only")

    assert store.users["only"].admin_role == "super_admin" and auditor.rows == []


async def test_a_super_admin_can_revoke_another_super_admin():
    service, store, *_ = build(*people())

    await service.revoke_admin(SUPER, "sa2")

    assert store.users["sa2"].admin_role is None
