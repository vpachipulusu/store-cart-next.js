from datetime import UTC, datetime
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform.user import LoginHistory, UserSettings
from app.repositories.me_preferences import PreferencesRepository, SettingsData


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


class RecordingSession:
    def __init__(self, *values):
        self.values = iter(values)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return Result(next(self.values))


async def test_missing_settings_returns_defaults_without_writing():
    session = RecordingSession(None)
    repository = PreferencesRepository(cast(AsyncSession, session))
    assert await repository.get_settings("user-a") == SettingsData(
        "system", True, "en", "UTC"
    )
    assert len(session.statements) == 1
    statement = session.statements[0]
    assert str(statement).startswith("SELECT")
    assert statement.compile().params["user_id_1"] == "user-a"


async def test_existing_settings_returns_persisted_values():
    settings = UserSettings(
        theme="dark", email_notifications=False, language="fr", timezone="Europe/Paris"
    )
    repository = PreferencesRepository(cast(AsyncSession, RecordingSession(settings)))
    assert await repository.get_settings("user-a") == SettingsData(
        "dark", False, "fr", "Europe/Paris"
    )


async def test_partial_upsert_preserves_omitted_fields_and_targets_user():
    settings = UserSettings(
        theme="dark", email_notifications=True, language="en", timezone="UTC"
    )
    session = RecordingSession(settings)
    repository = PreferencesRepository(cast(AsyncSession, session))
    assert (
        await repository.update_settings("user-a", {"theme": "dark"})
    ).theme == "dark"
    statement = session.statements[0]
    sql = str(statement)
    assert "ON CONFLICT (user_id) DO UPDATE" in sql
    update = sql.split("DO UPDATE SET")[1].split("RETURNING")[0]
    assert "theme" in update and "updated_at" in update
    assert "email_notifications" not in update and "language" not in update
    assert statement.compile().params["user_id"] == "user-a"


async def test_history_count_and_rows_are_scoped_and_paginated_deterministically():
    timestamp = datetime.now(UTC)
    row = LoginHistory(
        id="login-a",
        user_id="user-a",
        ip_address=None,
        user_agent="browser",
        location=None,
        login_at=timestamp,
        successful=False,
    )
    session = RecordingSession(8, [row])
    repository = PreferencesRepository(cast(AsyncSession, session))
    page = await repository.get_login_history("user-a", 2, 4)
    assert page.total_count == 8
    assert page.login_history[0].login_at == timestamp
    assert page.login_history[0].successful is False
    for statement in session.statements:
        assert statement.compile().params["user_id_1"] == "user-a"
        assert "WHERE" in str(statement)
    statement = session.statements[1]
    assert "login_at DESC" in str(statement) and "id DESC" in str(statement)
    assert statement.compile().params["param_1"] == 2
    assert statement.compile().params["param_2"] == 4


async def test_empty_history_keeps_count_and_empty_page():
    repository = PreferencesRepository(cast(AsyncSession, RecordingSession(0, [])))
    page = await repository.get_login_history("user-a", 10, 0)
    assert page.total_count == 0 and page.login_history == []
