import pytest

from app.core.permissions import (
    ADMIN_PERMISSIONS,
    assert_can_grant,
    effective_permissions,
    validate_required,
)


def test_listed_permissions_are_granted_to_an_admin():
    assert effective_permissions("admin", ["users.read", "seo.read"]) == {
        "users.read",
        "seo.read",
    }


def test_wildcard_expands_to_every_known_permission_for_super_admin():
    assert effective_permissions("super_admin", ["*"]) == ADMIN_PERMISSIONS


def test_wildcard_is_ignored_for_a_plain_admin():
    assert effective_permissions("admin", ["*"]) == frozenset()


def test_wildcard_is_ignored_for_an_unknown_role():
    assert effective_permissions("owner", ["*", "users.read"]) == {"users.read"}


@pytest.mark.parametrize("stored", [None, "*", "users.read", {"users.read": True}, 7])
def test_non_list_permissions_grant_nothing(stored):
    assert effective_permissions("super_admin", stored) == frozenset()


def test_unknown_and_non_string_entries_are_dropped():
    stored = ["users.read", "users.*", "root.everything", 5, None, ["users.read"]]
    assert effective_permissions("admin", stored) == {"users.read"}


def test_empty_grant_is_empty():
    assert effective_permissions("super_admin", []) == frozenset()


def test_validate_required_rejects_an_empty_declaration():
    with pytest.raises(ValueError):
        validate_required(())


@pytest.mark.parametrize("name", ["*", "users.typo", ""])
def test_validate_required_rejects_unknown_and_wildcard_names(name):
    with pytest.raises(ValueError):
        validate_required((name,))


def test_validate_required_returns_the_declared_set():
    assert validate_required(("users.read", "users.update")) == {
        "users.read",
        "users.update",
    }


def _actor(role, permissions):
    from app.core.permissions import AdminContext

    return AdminContext("a-1", role, frozenset(permissions))


def test_grant_requires_admins_create():
    assert not assert_can_grant(
        _actor("admin", ["users.read"]), "admin", ["users.read"]
    )


def test_admin_can_grant_only_permissions_it_holds():
    actor = _actor("admin", ["admins.create", "users.read"])
    assert assert_can_grant(actor, "admin", ["users.read"])
    assert not assert_can_grant(actor, "admin", ["users.read", "users.delete"])


def test_admin_cannot_grant_wildcard_or_super_admin_to_anyone():
    actor = _actor("admin", ["admins.create"])
    assert not assert_can_grant(actor, "admin", ["*"])
    assert not assert_can_grant(actor, "super_admin", [])


def test_super_admin_may_grant_wildcard_and_super_admin():
    actor = _actor("super_admin", sorted(ADMIN_PERMISSIONS))
    assert assert_can_grant(actor, "super_admin", ["*"])


@pytest.mark.parametrize(
    "permissions", [None, "users.read", ["users.read", 3], ["nope.x"]]
)
def test_malformed_or_unknown_grants_are_refused(permissions):
    actor = _actor("super_admin", sorted(ADMIN_PERMISSIONS))
    assert not assert_can_grant(actor, "admin", permissions)
