from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.me_export import AccountExport, ExportProfile, ExportSettings
from app.services.me_export import ExportNotAvailable, MeExportService

NOW = datetime(2026, 1, 1, tzinfo=UTC)
EXPORT = AccountExport(
    ExportProfile(
        "u1",
        "ada@example.com",
        True,
        False,
        "Ada",
        None,
        None,
        None,
        None,
        None,
        None,
        NOW,
    ),
    ExportSettings("system", True, "en", "UTC"),
    [],
    [],
    [],
)


class Repo:
    def __init__(self, user_id="u1", export=EXPORT):
        self.user_id, self.export = user_id, export

    async def user_id_for_uid(self, uid):
        return self.user_id

    async def collect(self, user_id):
        return self.export


class Audit:
    def __init__(self, fail=False):
        self.rows: list[dict[str, Any]] = []
        self.fail = fail

    async def add(self, **row):
        if self.fail:
            raise RuntimeError("audit down")
        self.rows.append(row)


class Session:
    def __init__(self):
        self.events = []

    async def commit(self):
        self.events.append("commit")

    async def rollback(self):
        self.events.append("rollback")


def service(repo, audit, session):
    return MeExportService(repo, audit, cast(AsyncSession, session))


async def test_export_writes_audit_row_with_counts_only_then_commits():
    audit, session = Audit(), Session()
    result = await service(Repo(), audit, session).export(
        "uid", ip_address="1.1.1.1", user_agent="UA" * 400, request_id="r1"
    )
    assert result is EXPORT
    row = audit.rows[0]
    assert row["action"] == "me.export"
    assert row["user_id"] == row["resource_id"] == "u1"
    assert row["metadata"]["details"]["notifications"] == 0
    assert "ada@example.com" not in str(row)
    assert len(row["user_agent"]) == 512
    assert session.events == ["commit"]


async def test_audit_failure_fails_export_and_rolls_back():
    session = Session()
    with pytest.raises(RuntimeError):
        await service(Repo(), Audit(fail=True), session).export(
            "uid", ip_address=None, user_agent=None, request_id=None
        )
    assert session.events == ["rollback"]


@pytest.mark.parametrize("repo", [Repo(user_id=None), Repo(export=None)])
async def test_missing_user_raises_and_writes_no_audit(repo):
    audit, session = Audit(), Session()
    with pytest.raises(ExportNotAvailable):
        await service(repo, audit, session).export(
            "uid", ip_address=None, user_agent=None, request_id=None
        )
    assert audit.rows == [] and session.events == ["rollback"]
