from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.repositories.totp import TotpRepository


class FakeSession:
    def __init__(self, row=None):
        self.row = row
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(one_or_none=lambda: self.row)


async def test_read_is_uid_scoped_and_locks_row():
    session = FakeSession(
        SimpleNamespace(
            id="user", two_factor_enabled=False, two_factor_secret="encrypted"
        )
    )
    state = await TotpRepository(session).lock_user("firebase-uid")
    statement = session.statements[0].compile(dialect=postgresql.dialect())
    assert "FOR UPDATE" in str(statement)
    assert "firebase_uid" in str(statement)
    assert statement.params == {"firebase_uid_1": "firebase-uid"}
    assert state.user_id == "user" and state.ciphertext == "encrypted"


async def test_missing_user_returns_none():
    assert await TotpRepository(FakeSession()).lock_user("uid") is None


async def test_disable_clears_only_target_users_secret():
    session = FakeSession()
    await TotpRepository(session).set_state("user", False, None)
    statement = session.statements[0].compile(dialect=postgresql.dialect())
    assert "users.id =" in str(statement)
    assert statement.params["two_factor_secret"] is None
    assert statement.params["two_factor_enabled"] is False
    assert statement.params["id_1"] == "user"
