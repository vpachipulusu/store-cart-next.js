from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.repositories.me import MeRepository
from tests.api.test_me import PROFILE


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value


class Session:
    def __init__(self, value):
        self.value = value
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return Result(self.value)


def sql(statement):
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


async def test_profile_lookup_uses_uid_and_lock_without_exposing_secret():
    user = SimpleNamespace(
        **{key: getattr(PROFILE, key) for key in PROFILE.__dataclass_fields__},
        two_factor_secret="private",
        firebase_uid="firebase-user",
    )
    session = Session(user)
    assert (
        await MeRepository(session).get_profile("firebase-user", lock=True) == PROFILE
    )
    text, params = sql(session.statements[0])
    assert "users.firebase_uid =" in text and "FOR UPDATE" in text
    assert "firebase-user" in params.values()


async def test_missing_user_returns_none():
    assert await MeRepository(Session(None)).get_profile("missing") is None


async def test_profile_update_and_delete_are_scoped_to_platform_id():
    session = Session(PROFILE)
    repository = MeRepository(session)
    assert (
        await repository.update_profile("platform-user", {"bio": "new"})
    ).id == "platform-user"
    await repository.delete_user("platform-user")
    for statement in session.statements:
        text, params = sql(statement)
        assert "users.id =" in text and "platform-user" in params.values()


async def test_owner_membership_check_is_scoped_and_locked():
    session = Session(["STAFF", "OWNER"])
    assert await MeRepository(session).has_owner_membership("platform-user")
    text, params = sql(session.statements[0])
    assert "memberships.user_id =" in text and "FOR UPDATE" in text
    assert "platform-user" in params.values()
    session.value = ["STAFF", "ADMIN"]
    assert not await MeRepository(session).has_owner_membership("platform-user")
