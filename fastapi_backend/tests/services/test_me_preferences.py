from contextlib import asynccontextmanager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.me_preferences import HistoryPage, SettingsData
from app.services.me_preferences import PreferencesService


class Repository:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def get_settings(self, user_id):
        self.calls.append(("get", user_id))
        return SettingsData("system", True, "en", "UTC")

    async def update_settings(self, user_id, changes):
        self.calls.append(("update", user_id, changes))
        if self.fail:
            raise RuntimeError("storage unavailable")
        return SettingsData("dark", True, "en", "UTC")

    async def get_login_history(self, user_id, limit, offset):
        self.calls.append(("history", user_id, limit, offset))
        return HistoryPage([], 0)


class Session:
    def __init__(self, active=False):
        self.active = active
        self.events = []

    def in_transaction(self):
        return self.active

    @asynccontextmanager
    async def begin(self):
        self.events.append("begin")
        try:
            yield
        except Exception:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")

    async def commit(self):
        self.events.append("commit")

    async def rollback(self):
        self.events.append("rollback")


def service(repository, session):
    return PreferencesService(repository, cast(AsyncSession, session))


async def test_settings_read_has_no_write_transaction():
    repository, session = Repository(), Session()
    assert (await service(repository, session).get_settings("user-a")).theme == "system"
    assert repository.calls == [("get", "user-a")]
    assert session.events == []


@pytest.mark.parametrize("active", [False, True])
async def test_update_commits_using_existing_or_new_transaction(active):
    repository, session = Repository(), Session(active)
    result = await service(repository, session).update_settings(
        "user-a", {"theme": "dark"}
    )
    assert result.theme == "dark"
    assert repository.calls == [("update", "user-a", {"theme": "dark"})]
    assert session.events == (["commit"] if active else ["begin", "commit"])


@pytest.mark.parametrize("active", [False, True])
async def test_storage_failure_rolls_back_and_propagates(active):
    repository, session = Repository(), Session(active)
    repository.fail = True
    with pytest.raises(RuntimeError):
        await service(repository, session).update_settings("user-a", {"theme": "dark"})
    assert session.events[-1] == "rollback"
    assert "commit" not in session.events


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"user_id": "other"},
        {"theme": "invalid"},
        {"theme": None},
        {"email_notifications": "false"},
        {"language": "x"},
        {"language": "too-long"},
        {"timezone": ""},
        {"timezone": "x" * 101},
    ],
)
async def test_invalid_updates_never_reach_repository(changes):
    repository, session = Repository(), Session()
    with pytest.raises(ValueError):
        await service(repository, session).update_settings("user-a", changes)
    assert repository.calls == [] and session.events == []


async def test_history_delegates_trusted_id_and_pagination():
    repository, session = Repository(), Session()
    assert await service(repository, session).get_login_history(
        "user-a", 10, 20
    ) == HistoryPage([], 0)
    assert repository.calls == [("history", "user-a", 10, 20)]


@pytest.mark.parametrize(
    "limit,offset", [(0, 0), (101, 0), (10, -1), (True, 0), (10, False)]
)
async def test_invalid_pagination_never_reaches_repository(limit, offset):
    repository, session = Repository(), Session()
    with pytest.raises(ValueError):
        await service(repository, session).get_login_history("user-a", limit, offset)
    assert repository.calls == []
