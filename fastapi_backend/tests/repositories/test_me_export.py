from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform.user import User
from app.repositories.me_export import MeExportRepository

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value


class Session:
    def __init__(self, *values):
        self.values = iter(values)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return Result(next(self.values))


def repo(session):
    return MeExportRepository(cast(AsyncSession, session))


async def test_user_id_lookup_by_uid():
    session = Session("u1")
    assert await repo(session).user_id_for_uid("uid") == "u1"
    assert session.statements[0].compile().params["firebase_uid_1"] == "uid"


async def test_collect_missing_user_is_none():
    assert await repo(Session(None)).collect("u1") is None


async def test_collect_maps_rows_without_secrets_and_scopes_to_user():
    user = User(
        id="u1",
        firebase_uid="SECRET-UID",
        email="a@b.c",
        email_verified=True,
        two_factor_enabled=True,
        two_factor_secret="TOTP-SECRET",
        created_at=NOW,
    )
    org = SimpleNamespace(
        id="o1",
        name="Org",
        slug="org",
        subscription_tier="pro",
        subscription_status="active",
        stripe_current_period_end=None,
        stripe_cancel_at_period_end=False,
        stripe_customer_id="cus_SECRET",
    )
    member = SimpleNamespace(role="OWNER", created_at=NOW)
    login = SimpleNamespace(
        id="l1",
        ip_address="1.1.1.1",
        user_agent=None,
        location=None,
        login_at=NOW,
        successful=True,
    )
    note = SimpleNamespace(
        id="n1",
        type="t",
        title="T",
        message="M",
        read=False,
        link=None,
        organization_id=None,
        store_id=None,
        created_at=NOW,
    )
    session = Session(user, None, [(member, org)], [login], [note])
    export = await repo(session).collect("u1")
    assert export is not None
    assert export.settings.theme == "system"  # defaults when no settings row
    assert export.memberships[0].organization_slug == "org"
    assert export.login_history[0].ip_address == "1.1.1.1"
    assert export.notifications[0].id == "n1"
    dumped = repr(export)
    for secret in ("SECRET-UID", "TOTP-SECRET", "cus_SECRET"):
        assert secret not in dumped
    for statement in session.statements[1:]:
        assert "u1" in statement.compile().params.values()


async def test_collect_flags_and_trims_lists_over_the_cap():
    from app.repositories.me_export import MAX_EXPORT_ROWS

    user = User(id="u1", email="a@b.c", email_verified=True, created_at=NOW)
    logins = [
        SimpleNamespace(
            id=f"l{i}",
            ip_address=None,
            user_agent=None,
            location=None,
            login_at=NOW,
            successful=True,
        )
        for i in range(MAX_EXPORT_ROWS + 1)
    ]
    session = Session(user, None, [], logins, [])
    export = await repo(session).collect("u1")
    assert export is not None
    assert export.truncated is True
    assert len(export.login_history) == MAX_EXPORT_ROWS
    assert session.statements[3].compile().params["param_1"] == MAX_EXPORT_ROWS + 1
