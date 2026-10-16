from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.notifications import NotificationPage, NotificationScope
from app.services.notifications import NotificationNotFound, NotificationsService


class Repository:
    def __init__(self, found=True):
        self.found = found
        self.fail = False
        self.calls = []

    async def list_for_user(self, user_id, scope, unread_only, limit, offset):
        self.calls.append(("list", user_id, scope, unread_only, limit, offset))
        return NotificationPage([], 0, 0)

    async def mark_read(self, user_id, notification_id):
        self.calls.append(("read", user_id, notification_id))

    async def mark_all_read(self, user_id, scope):
        self.calls.append(("read-all", user_id, scope))
        if self.fail:
            raise RuntimeError("storage unavailable")
        return 3

    async def delete(self, user_id, notification_id):
        self.calls.append(("delete", user_id, notification_id))
        return self.found


class Session:
    def __init__(self):
        self.events = []

    async def commit(self):
        self.events.append("commit")

    async def rollback(self):
        self.events.append("rollback")


def service(repository, session):
    return NotificationsService(repository, cast(AsyncSession, session))


async def test_list_passes_the_user_and_scope_without_a_write():
    repository, session = Repository(), Session()
    scope = NotificationScope("org-1", None)

    await service(repository, session).list_notifications("u1", scope, True, 5, 10)

    assert repository.calls == [("list", "u1", scope, True, 5, 10)]
    assert session.events == []


async def test_mark_all_read_commits_and_returns_the_count():
    repository, session = Repository(), Session()

    updated = await service(repository, session).mark_all_read(
        "u1", NotificationScope()
    )

    assert updated == 3
    assert session.events == ["commit"]


async def test_mark_all_read_failure_rolls_back_and_propagates():
    repository, session = Repository(), Session()
    repository.fail = True

    with pytest.raises(RuntimeError):
        await service(repository, session).mark_all_read("u1", NotificationScope())

    assert session.events == ["rollback"]


async def test_mark_read_of_a_missing_notification_raises_not_found():
    repository, session = Repository(), Session()

    with pytest.raises(NotificationNotFound):
        await service(repository, session).mark_read("u1", "n1")

    assert session.events == ["rollback"]


@pytest.mark.parametrize("found", [True, False])
async def test_delete_commits_only_when_a_row_was_removed(found):
    repository, session = Repository(found), Session()

    if found:
        await service(repository, session).delete("u1", "n1")
    else:
        with pytest.raises(NotificationNotFound):
            await service(repository, session).delete("u1", "n1")

    assert session.events == (["commit"] if found else ["rollback"])
    assert repository.calls == [("delete", "u1", "n1")]
