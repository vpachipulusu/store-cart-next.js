from datetime import UTC, datetime
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firebase import VerifiedIdentity
from app.repositories.auth import AuthRepository
from tests.fakes import FakeResult


class RecordingSession:
    def __init__(self):
        self.statements = []
        self.rows = []
        self.flushed = False

    async def execute(self, statement):
        self.statements.append(statement)
        return FakeResult("user-id")

    def add(self, row):
        self.rows.append(row)

    async def flush(self):
        self.flushed = True


async def test_upsert_targets_uid_not_email_and_preserves_existing_profile():
    session = RecordingSession()
    repo = AuthRepository(cast(AsyncSession, session))
    identity = VerifiedIdentity("uid", "ada@example.com", True, 123, "Ada")
    assert await repo.sync_user(identity, datetime.now(UTC)) == "user-id"
    sql = str(session.statements[0])
    assert "ON CONFLICT (firebase_uid) DO UPDATE" in sql
    update = sql.split("DO UPDATE SET")[1].split("RETURNING")[0]
    assert "display_name" not in update
    assert "email_verified" in update and "last_login_at" in update
    assert session.statements[0].compile().params["firebase_uid"] == "uid"


async def test_login_history_is_added_and_flushed_without_repository_commit():
    session = RecordingSession()
    repo = AuthRepository(cast(AsyncSession, session))
    await repo.record_login("user-id", "192.0.2.1", "browser")
    assert session.flushed
    row = session.rows[0]
    assert (row.user_id, row.ip_address, row.user_agent) == (
        "user-id",
        "192.0.2.1",
        "browser",
    )
