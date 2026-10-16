import time
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest

from app.core.config import settings
from app.core.firebase import (
    AuthenticationFailed,
    IdentityPasswordRejected,
    IdentityProviderUnavailable,
    IdentityUserNotFound,
    VerifiedIdentity,
)
from app.services.me import MeService, OwnershipConflict, UserNotFound
from tests.api.test_me import PROFILE


class Session:
    def __init__(self):
        self.committed = self.rolled_back = False
        self.commit_failure = False

    @asynccontextmanager
    async def begin(self):
        try:
            yield
            if self.commit_failure:
                raise RuntimeError("commit failed")
            self.committed = True
        except Exception:
            self.rolled_back = True
            raise


class Repository:
    def __init__(self, events):
        self.events = events
        self.profile = PROFILE
        self.owner = False

    async def get_profile(self, uid, *, lock=False):
        self.events.append(("profile", uid, lock))
        return self.profile

    async def update_profile(self, user_id, changes):
        self.events.append(("update", user_id, changes))
        return replace(self.profile, **changes)

    async def has_owner_membership(self, user_id):
        self.events.append(("owner", user_id))
        return self.owner

    async def delete_user(self, user_id):
        self.events.append(("sql-delete", user_id))


class Identity:
    def __init__(self, events):
        self.events = events
        self.claims = {
            "uid": "firebase-user",
            "email": "ada@example.com",
            "email_verified": True,
            "auth_time": int(time.time()),
            "firebase": {"sign_in_provider": "password"},
        }
        self.failure = None

    async def verify_id_token(self, token):
        self.events.append(("verify", token))
        return self.claims

    async def delete_user(self, uid):
        self.events.append(("firebase-delete", uid))
        if self.failure:
            raise self.failure

    async def update_password(self, uid, password):
        self.events.append(("password", uid, password))
        if self.failure:
            raise self.failure


@pytest.fixture
def context():
    events = []
    repository, session, identity = Repository(events), Session(), Identity(events)
    return (
        MeService(repository, session, identity),
        repository,
        session,
        identity,
        events,
    )


def current():
    return VerifiedIdentity("firebase-user", "ada@example.com", True, int(time.time()))


async def test_updates_profile_in_locked_transaction(context):
    service, _, session, _, events = context
    result = await service.update_profile("firebase-user", {"bio": "new"})
    assert result.bio == "new" and result.display_name == "Ada"
    assert events == [
        ("profile", "firebase-user", True),
        ("update", "platform-user", {"bio": "new"}),
    ]
    assert session.committed


@pytest.mark.parametrize(
    "changes", [{}, {"email": "bad"}, {"two_factor_secret": "secret"}]
)
async def test_service_rejects_mass_assignment(context, changes):
    with pytest.raises(ValueError):
        await context[0].update_profile("firebase-user", changes)
    assert not context[4]


async def test_missing_user_is_explicit_and_update_rolls_back(context):
    service, repository, session, _, _ = context
    repository.profile = None
    with pytest.raises(UserNotFound):
        await service.get_profile("uid")
    with pytest.raises(UserNotFound):
        await service.update_profile("uid", {"bio": None})
    assert session.rolled_back


async def test_deletion_checks_owner_and_deletes_firebase_before_sql(context):
    service, _, session, _, events = context
    await service.delete_account(current(), "fresh")
    assert events == [
        ("verify", "fresh"),
        ("profile", "firebase-user", True),
        ("owner", "platform-user"),
        ("firebase-delete", "firebase-user"),
        ("sql-delete", "platform-user"),
    ]
    assert session.committed


@pytest.mark.parametrize(
    "changed",
    [
        {"uid": "another"},
        {"email_verified": False},
        {"auth_time": -301},
        {"auth_time": 300},
        {"auth_time": True},
    ],
)
async def test_stale_future_unverified_and_foreign_reauthentication_never_reaches_database(
    context, changed
):
    service, _, _, identity, events = context
    if type(changed.get("auth_time")) is int:
        # Offsets are resolved at run time: a suite longer than 300s must not age them.
        changed = {"auth_time": int(time.time()) + changed["auth_time"]}
    identity.claims.update(changed)
    with pytest.raises(AuthenticationFailed):
        await service.delete_account(current(), "token")
    assert events == [("verify", "token")]


async def test_owner_cannot_delete_account_or_billing(context):
    service, repository, session, _, events = context
    repository.owner = True
    with pytest.raises(OwnershipConflict):
        await service.delete_account(current(), "token")
    assert session.rolled_back
    assert not any("delete" in event[0] for event in events)


async def test_missing_account_cannot_trigger_external_deletion(context):
    service, repository, _, _, events = context
    repository.profile = None
    with pytest.raises(UserNotFound):
        await service.delete_account(current(), "token")
    assert len(events) == 2


async def test_firebase_failure_rolls_back_and_preserves_database_user(context):
    service, _, session, identity, events = context
    identity.failure = IdentityProviderUnavailable()
    with pytest.raises(IdentityProviderUnavailable):
        await service.delete_account(current(), "token")
    assert session.rolled_back and not session.committed
    assert not any(event[0] == "sql-delete" for event in events)


async def test_sql_commit_failure_after_firebase_success_propagates(context):
    service, _, session, _, events = context
    session.commit_failure = True
    with pytest.raises(RuntimeError):
        await service.delete_account(current(), "token")
    assert session.rolled_back and not session.committed
    assert events[-2:] == [
        ("firebase-delete", "firebase-user"),
        ("sql-delete", "platform-user"),
    ]


async def test_password_change_verifies_fresh_reauthentication_then_updates_firebase(
    context,
):
    service, _, _, _, events = context
    await service.change_password(current(), "fresh", "new-password-1")
    assert events == [
        ("verify", "fresh"),
        ("profile", "firebase-user", False),
        ("password", "firebase-user", "new-password-1"),
    ]


@pytest.mark.parametrize(
    "changed",
    [
        {"uid": "another"},
        {"email_verified": False},
        {"auth_time": -301},
        {"auth_time": 300},
    ],
)
async def test_password_change_rejects_stale_foreign_or_unverified_reauthentication(
    context, changed
):
    service, _, _, identity, events = context
    if "auth_time" in changed:
        changed = {"auth_time": int(time.time()) + changed["auth_time"]}
    identity.claims.update(changed)
    with pytest.raises(AuthenticationFailed):
        await service.change_password(current(), "token", "new-password-1")
    assert events == [("verify", "token")]


async def test_password_change_for_a_missing_account_never_reaches_firebase(context):
    service, repository, _, _, events = context
    repository.profile = None
    with pytest.raises(UserNotFound):
        await service.change_password(current(), "token", "new-password-1")
    assert not any(event[0] == "password" for event in events)


async def test_password_change_maps_a_vanished_firebase_user_to_not_found(context):
    service, _, _, identity, _ = context
    identity.failure = IdentityUserNotFound()
    with pytest.raises(UserNotFound):
        await service.change_password(current(), "token", "new-password-1")


async def test_password_change_propagates_provider_outages(context):
    service, _, _, identity, _ = context
    identity.failure = IdentityProviderUnavailable()
    with pytest.raises(IdentityProviderUnavailable):
        await service.change_password(current(), "token", "new-password-1")


@pytest.mark.parametrize(
    "firebase", [{"sign_in_provider": "google.com"}, {}, None, "password"]
)
async def test_password_change_requires_a_password_provider_reauthentication(
    context, firebase
):
    service, _, _, identity, events = context
    identity.claims["firebase"] = firebase
    with pytest.raises(AuthenticationFailed):
        await service.change_password(current(), "token", "new-password-1")
    assert events == [("verify", "token")]


async def test_account_deletion_does_not_require_the_password_provider(context):
    service, _, _, identity, _ = context
    identity.claims["firebase"] = {"sign_in_provider": "google.com"}
    await service.delete_account(current(), "token")


async def test_password_change_propagates_a_rejected_password(context):
    service, _, _, identity, _ = context
    identity.failure = IdentityPasswordRejected()
    with pytest.raises(IdentityPasswordRejected):
        await service.change_password(current(), "token", "new-password-1")


@pytest.mark.parametrize("offset,accepted", [(10, True), (11, False)])
async def test_reauthentication_tolerates_future_auth_time_up_to_the_skew(
    context, monkeypatch, offset, accepted
):
    monkeypatch.setattr(settings, "FIREBASE_CLOCK_SKEW_SECONDS", 10)
    monkeypatch.setattr("app.services.auth.time.time", lambda: 1_000_000.0)
    service, _, _, identity, _ = context
    identity.claims["auth_time"] = 1_000_000 + offset
    if accepted:
        await service.delete_account(current(), "token")
    else:
        with pytest.raises(AuthenticationFailed):
            await service.delete_account(current(), "token")


@pytest.mark.parametrize("age,accepted", [(300, True), (301, False)])
async def test_reauthentication_age_edges_with_a_pinned_clock(
    context, monkeypatch, age, accepted
):
    monkeypatch.setattr("app.services.auth.time.time", lambda: 1_000_000.0)
    service, _, _, identity, _ = context
    identity.claims["auth_time"] = 1_000_000 - age
    if accepted:
        await service.delete_account(current(), "token")
    else:
        with pytest.raises(AuthenticationFailed):
            await service.delete_account(current(), "token")
