"""End to end: team members and invitations on a real Postgres (KAN-62).

Same contract as ``test_organizations_e2e.py``: runs only when ``TEST_DATABASE_URL`` points
at a throwaway local ``*_test`` database, rebuilt with the real Alembic migrations. Only
Firebase (the identity comes from ``X-Test-Uid`` and ``X-Test-Email``), the email sender
(a recorder) and the clock (a settable one) are replaced. Routes, role checks, the
organisation lock, the conditional accept, plan limits and audit rows are production code.
"""

import asyncio
import hashlib
import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import pytest
from fastapi import Header, HTTPException
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api.auth import get_session_identity
from app.api.deps import SessionDep, get_session_provider
from app.api.v1.invitations import get_invitations_service
from app.core.database import DefaultSessionProvider, build_engine
from app.core.firebase import VerifiedIdentity
from app.core.ids import new_id
from app.main import create_app
from app.repositories.invitations import InvitationsRepository
from app.repositories.organizations import OrganizationsRepository
from app.services.email import (
    DisabledEmailSender,
    EmailDeliveryFailed,
    EmailMessage,
)
from app.services.invitations import InvitationsService

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND_ROOT = Path(__file__).resolve().parents[2]
KEY = "test-only-internal-service-key-not-for-deployment"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
APP_URL = "https://app.example.com"
LINK = re.compile(r"^https://app\.example\.com/invite/([A-Za-z0-9_-]{40,})$")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)


def _migrate(url: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env={**os.environ, "DATABASE_URL_DIRECT": url},
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    assert TEST_DATABASE_URL is not None
    target = make_url(TEST_DATABASE_URL)
    assert (target.database or "").endswith("_test"), (
        "refusing to rebuild a database whose name does not end in _test"
    )
    assert target.host in LOCAL_HOSTS, "refusing to rebuild a non-local database"
    _migrate(TEST_DATABASE_URL, "downgrade", "base")
    _migrate(TEST_DATABASE_URL, "upgrade", "head")
    yield TEST_DATABASE_URL


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    built = build_engine(database_url)
    async with built.begin() as connection:
        await connection.execute(
            text("TRUNCATE users, organizations, audit_logs CASCADE")
        )
    yield built
    await built.dispose()


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []
        self.fail = False

    async def send(self, message: EmailMessage) -> None:
        if self.fail:
            raise EmailDeliveryFailed
        self.sent.append(message)


class World:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.clock = Clock()
        self.sender: RecordingSender | DisabledEmailSender = RecordingSender()
        self.app_url: str | None = APP_URL


@pytest.fixture
def world(engine: AsyncEngine) -> World:
    return World(engine)


@pytest.fixture
async def client(world: World) -> AsyncIterator[AsyncClient]:
    app = create_app()
    provider = DefaultSessionProvider(
        async_sessionmaker(world.engine, expire_on_commit=False)
    )
    app.dependency_overrides[get_session_provider] = lambda: provider

    async def identity(
        x_test_uid: Annotated[str | None, Header()] = None,
        x_test_email: Annotated[str | None, Header()] = None,
    ) -> VerifiedIdentity:
        if x_test_uid is None:
            raise HTTPException(401, "Invalid authentication")
        email = x_test_email or f"{x_test_uid.removeprefix('fb-')}@example.com"
        return VerifiedIdentity(x_test_uid, email, True, int(time.time()))

    def service(session: SessionDep) -> InvitationsService:
        return InvitationsService(
            InvitationsRepository(session),
            OrganizationsRepository(session),
            session,
            world.sender,
            world.app_url,
            clock=world.clock,
        )

    app.dependency_overrides[get_session_identity] = identity
    app.dependency_overrides[get_invitations_service] = service
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-Internal-Key": KEY}
    ) as http:
        yield http


async def seed_user(engine: AsyncEngine, name: str) -> str:
    async with engine.begin() as connection:
        found = (
            await connection.execute(
                text("SELECT id FROM users WHERE firebase_uid = :uid"),
                {"uid": f"fb-{name}"},
            )
        ).scalar_one_or_none()
        if found:
            return str(found)
        user_id = new_id()
        await connection.execute(
            text(
                "INSERT INTO users (id, firebase_uid, email, email_verified) "
                "VALUES (:id, :uid, :email, true)"
            ),
            {"id": user_id, "uid": f"fb-{name}", "email": f"{name}@example.com"},
        )
        return user_id


async def seed_org(
    engine: AsyncEngine, members: dict[str, str], tier: str = "pro"
) -> str:
    org_id = new_id()
    user_ids = {user: await seed_user(engine, user) for user in members}
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO organizations (id, name, slug, subscription_tier) "
                "VALUES (:id, :n, :s, :t)"
            ),
            {"id": org_id, "n": "Acme <b>Shop</b>", "s": f"acme-{org_id}", "t": tier},
        )
        for user, role in members.items():
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (:id, :org, :user, :role)"
                ),
                {"id": new_id(), "org": org_id, "user": user_ids[user], "role": role},
            )
    return org_id


async def scalar(engine: AsyncEngine, sql: str, **params: Any) -> Any:
    async with engine.connect() as connection:
        return (await connection.execute(text(sql), params)).scalar_one()


def as_user(name: str, email: str | None = None) -> dict[str, str]:
    headers = {"X-Test-Uid": f"fb-{name}"}
    if email is not None:
        headers["X-Test-Email"] = email
    return headers


def error_of(response: Response) -> str:
    body = response.json()
    assert body["success"] is False
    return str(body["error"])


async def invite(
    client: AsyncClient,
    org_id: str,
    email: str,
    role: str = "STAFF",
    user: str = "owner",
) -> Response:
    return await client.post(
        f"/v1/organizations/{org_id}/invitations",
        json={"email": email, "role": role},
        headers=as_user(user),
    )


def token_of(response: Response) -> str:
    match = LINK.match(response.json()["data"]["accept_url"])
    assert match is not None
    return match.group(1)


async def accept(
    client: AsyncClient, token: str, user: str, email: str | None = None
) -> Response:
    return await client.post(
        "/v1/invitations/accept",
        json={"token": token},
        headers=as_user(user, email),
    )


# --- create -------------------------------------------------------------------


@pytest.mark.parametrize("inviter", ["owner", "admin"])
async def test_owner_and_admin_invite_by_email(client, world, inviter):
    org_id = await seed_org(world.engine, {"owner": "OWNER", "admin": "ADMIN"})

    response = await invite(client, org_id, "New@Example.com", user=inviter)

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    data = response.json()["data"]
    assert data["email"] == "new@example.com"
    assert data["role"] == "STAFF"
    assert data["email_sent"] is True
    assert LINK.match(data["accept_url"])
    [message] = world.sender.sent
    assert message.to == "new@example.com"
    assert data["accept_url"] in message.text
    assert "Acme &lt;b&gt;Shop&lt;/b&gt;" in message.html


async def test_invitation_expires_seven_days_after_creation(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})

    response = await invite(client, org_id, "new@example.com")

    expires = datetime.fromisoformat(response.json()["data"]["expires_at"])
    assert abs(expires - (world.clock.now + timedelta(days=7))) < timedelta(seconds=1)


async def test_only_the_token_hash_is_stored(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})

    token = token_of(await invite(client, org_id, "new@example.com"))

    stored = await scalar(world.engine, "SELECT token_hash FROM invitations")
    assert stored == hashlib.sha256(token.encode()).hexdigest()
    assert token not in stored
    dump = await scalar(
        world.engine, "SELECT string_agg(metadata::text, ' ') FROM audit_logs"
    )
    assert token not in dump
    assert "new@example.com" not in dump


async def test_staff_cannot_invite(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER", "staff": "STAFF"})

    response = await invite(client, org_id, "new@example.com", user="staff")

    assert response.status_code == 403
    assert await scalar(world.engine, "SELECT count(*) FROM invitations") == 0


async def test_non_member_gets_404(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    await seed_org(world.engine, {"stranger": "OWNER"})

    response = await invite(client, org_id, "new@example.com", user="stranger")

    assert response.status_code == 404
    assert error_of(response) == "Organization not found"


async def test_nobody_can_be_invited_as_owner(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})

    response = await invite(client, org_id, "new@example.com", role="OWNER")

    assert response.status_code == 422
    assert await scalar(world.engine, "SELECT count(*) FROM invitations") == 0


async def test_invalid_email_is_422(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})

    response = await invite(client, org_id, "not-an-email")

    assert response.status_code == 422


async def test_inviting_an_existing_member_is_409(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER", "staff": "STAFF"})

    response = await invite(client, org_id, "STAFF@example.com")

    assert response.status_code == 409
    assert error_of(response) == "Already a member of this organization"


async def test_second_pending_invitation_for_one_email_is_409(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    await invite(client, org_id, "new@example.com")

    response = await invite(client, org_id, "NEW@example.com")

    assert response.status_code == 409


async def test_expired_invitation_can_be_replaced(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    await invite(client, org_id, "new@example.com")
    world.clock.advance(timedelta(days=7, seconds=1))

    response = await invite(client, org_id, "new@example.com")

    assert response.status_code == 201
    statuses = await scalar(
        world.engine,
        "SELECT string_agg(status, ',' ORDER BY created_at) FROM invitations",
    )
    assert statuses == "EXPIRED,PENDING"


async def test_invite_beyond_the_staff_limit_is_409(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"}, tier="free")

    response = await invite(client, org_id, "new@example.com")

    assert response.status_code == 409
    assert "Free plan allows 1 team member" in error_of(response)


async def test_open_invitations_hold_a_seat(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER", "admin": "ADMIN"})
    for name in ("a", "b", "c"):
        assert (await invite(client, org_id, f"{name}@example.com")).status_code == 201

    # Pro allows 5: two members and three open invitations fill it.
    response = await invite(client, org_id, "d@example.com")

    assert response.status_code == 409
    assert "Pro plan allows 5 team members" in error_of(response)


async def test_pending_invitations_are_capped(client, world, monkeypatch):
    monkeypatch.setattr("app.services.invitations.MAX_PENDING_INVITATIONS", 2)
    org_id = await seed_org(world.engine, {"owner": "OWNER"}, tier="enterprise")
    await invite(client, org_id, "a@example.com")
    await invite(client, org_id, "b@example.com")

    response = await invite(client, org_id, "c@example.com")

    assert response.status_code == 409
    assert error_of(response) == "Too many pending invitations"


async def test_failed_email_still_returns_the_link(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    world.sender.fail = True

    response = await invite(client, org_id, "new@example.com")

    assert response.status_code == 201
    assert response.json()["data"]["email_sent"] is False
    assert LINK.match(response.json()["data"]["accept_url"])


async def test_disabled_email_reports_not_sent(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    world.sender = DisabledEmailSender()

    response = await invite(client, org_id, "new@example.com")

    assert response.status_code == 201
    assert response.json()["data"]["email_sent"] is False


async def test_unconfigured_app_url_is_503(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    world.app_url = None

    response = await invite(client, org_id, "new@example.com")

    assert response.status_code == 503
    assert await scalar(world.engine, "SELECT count(*) FROM invitations") == 0


async def test_create_is_audited_without_email_or_token(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})

    response = await invite(client, org_id, "new@example.com", role="ADMIN")

    action = await scalar(world.engine, "SELECT action FROM audit_logs")
    resource_id = await scalar(world.engine, "SELECT resource_id FROM audit_logs")
    assert action == "invitation.create"
    assert resource_id == response.json()["data"]["id"]


async def test_the_link_is_never_logged(client, world, caplog):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    caplog.set_level(logging.DEBUG)

    token = token_of(await invite(client, org_id, "new@example.com"))
    await seed_user(world.engine, "new")
    assert (await accept(client, token, "new")).status_code == 200
    assert (await accept(client, token, "new")).status_code == 410

    assert token not in caplog.text


# --- list ---------------------------------------------------------------------


async def test_lists_members_for_owner_and_admin(client, world):
    org_id = await seed_org(
        world.engine, {"owner": "OWNER", "admin": "ADMIN", "staff": "STAFF"}
    )

    response = await client.get(
        f"/v1/organizations/{org_id}/members", headers=as_user("admin")
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    members = {m["email"]: m["role"] for m in response.json()["data"]}
    assert members == {
        "owner@example.com": "OWNER",
        "admin@example.com": "ADMIN",
        "staff@example.com": "STAFF",
    }


@pytest.mark.parametrize("path", ["members", "invitations"])
async def test_staff_cannot_read_team(client, world, path):
    org_id = await seed_org(world.engine, {"owner": "OWNER", "staff": "STAFF"})

    response = await client.get(
        f"/v1/organizations/{org_id}/{path}", headers=as_user("staff")
    )

    assert response.status_code == 403


@pytest.mark.parametrize("path", ["members", "invitations"])
async def test_non_member_cannot_read_team(client, world, path):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    await seed_user(world.engine, "stranger")

    response = await client.get(
        f"/v1/organizations/{org_id}/{path}", headers=as_user("stranger")
    )

    assert response.status_code == 404


async def test_lists_pending_invitations_without_tokens(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    token = token_of(await invite(client, org_id, "new@example.com"))
    await invite(client, org_id, "old@example.com")
    used = token_of(await invite(client, org_id, "used@example.com"))
    await seed_user(world.engine, "used")
    await accept(client, used, "used")

    response = await client.get(
        f"/v1/organizations/{org_id}/invitations", headers=as_user("owner")
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert sorted(i["email"] for i in data) == ["new@example.com", "old@example.com"]
    assert set(data[0]) == {"id", "email", "role", "expires_at", "created_at"}
    stored = await scalar(
        world.engine,
        "SELECT min(token_hash) FROM invitations WHERE email = 'new@example.com'",
    )
    assert token not in response.text
    assert stored not in response.text


async def test_expired_invitations_are_not_listed(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    await invite(client, org_id, "new@example.com")
    world.clock.advance(timedelta(days=8))

    response = await client.get(
        f"/v1/organizations/{org_id}/invitations", headers=as_user("owner")
    )

    assert response.json()["data"] == []


# --- accept -------------------------------------------------------------------


async def test_accept_adds_the_member_with_the_invited_role(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    token = token_of(await invite(client, org_id, "new@example.com", role="ADMIN"))
    user_id = await seed_user(world.engine, "new")

    response = await accept(client, token, "new", "NEW@Example.com")

    assert response.status_code == 200
    assert response.json()["data"] == {"organization_id": org_id, "role": "ADMIN"}
    role = await scalar(
        world.engine,
        "SELECT role FROM memberships WHERE organization_id = :o AND user_id = :u",
        o=org_id,
        u=user_id,
    )
    assert role == "ADMIN"
    status = await scalar(world.engine, "SELECT status FROM invitations")
    assert status == "ACCEPTED"
    assert (
        await scalar(
            world.engine,
            "SELECT count(*) FROM audit_logs WHERE action = 'invitation.accept'",
        )
        == 1
    )


async def test_link_works_only_once(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    token = token_of(await invite(client, org_id, "new@example.com"))
    await seed_user(world.engine, "new")
    assert (await accept(client, token, "new")).status_code == 200

    response = await accept(client, token, "new")

    assert response.status_code == 410
    assert error_of(response) == "This invitation is invalid or has expired"


async def test_link_cannot_be_reused_by_another_account(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    token = token_of(await invite(client, org_id, "new@example.com"))
    await seed_user(world.engine, "new")
    assert (await accept(client, token, "new")).status_code == 200
    await seed_user(world.engine, "other")

    response = await accept(client, token, "other", "new@example.com")

    assert response.status_code == 410


async def test_expired_link_fails(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    token = token_of(await invite(client, org_id, "new@example.com"))
    await seed_user(world.engine, "new")
    world.clock.advance(timedelta(days=7, seconds=1))

    response = await accept(client, token, "new")

    assert response.status_code == 410
    assert await scalar(world.engine, "SELECT count(*) FROM memberships") == 1


async def test_link_still_works_just_before_expiry(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    token = token_of(await invite(client, org_id, "new@example.com"))
    await seed_user(world.engine, "new")
    world.clock.advance(timedelta(days=7) - timedelta(seconds=1))

    response = await accept(client, token, "new")

    assert response.status_code == 200


async def test_accept_is_bound_to_the_invited_email(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    token = token_of(await invite(client, org_id, "new@example.com"))
    await seed_user(world.engine, "intruder")

    response = await accept(client, token, "intruder")

    assert response.status_code == 403
    assert error_of(response) == (
        "This invitation was sent to a different email address"
    )
    assert await scalar(world.engine, "SELECT status FROM invitations") == "PENDING"


async def test_unknown_token_is_410(client, world):
    await seed_user(world.engine, "new")

    response = await accept(client, "x" * 43, "new")

    assert response.status_code == 410


async def test_malformed_token_is_422(client, world):
    await seed_user(world.engine, "new")

    response = await accept(client, "short", "new")

    assert response.status_code == 422


async def test_accept_requires_a_session(client, world):
    response = await client.post("/v1/invitations/accept", json={"token": "x" * 43})

    assert response.status_code == 401


async def test_accept_by_an_existing_member_is_409_and_keeps_the_link(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER", "staff": "STAFF"})
    async with world.engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO invitations (id, organization_id, email, role, token_hash,"
                " expires_at) VALUES (:id, :o, 'staff@example.com', 'ADMIN', :h, :e)"
            ),
            {
                "id": new_id(),
                "o": org_id,
                "h": hashlib.sha256(b"y" * 43).hexdigest(),
                "e": world.clock.now + timedelta(days=1),
            },
        )

    response = await accept(client, "y" * 43, "staff")

    assert response.status_code == 409
    assert await scalar(world.engine, "SELECT status FROM invitations") == "PENDING"


async def test_accept_beyond_the_staff_limit_is_409_and_keeps_the_link(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    token = token_of(await invite(client, org_id, "new@example.com"))
    await seed_user(world.engine, "new")
    async with world.engine.begin() as connection:
        await connection.execute(
            text("UPDATE organizations SET subscription_tier = 'free'")
        )

    response = await accept(client, token, "new")

    assert response.status_code == 409
    assert "Free plan allows 1 team member" in error_of(response)
    assert await scalar(world.engine, "SELECT status FROM invitations") == "PENDING"
    assert await scalar(world.engine, "SELECT count(*) FROM memberships") == 1


async def test_concurrent_accepts_admit_exactly_one(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"})
    token = token_of(await invite(client, org_id, "new@example.com"))
    await seed_user(world.engine, "new")

    responses = await asyncio.gather(*(accept(client, token, "new") for _ in range(5)))

    assert sorted(r.status_code for r in responses) == [200, 410, 410, 410, 410]
    assert await scalar(world.engine, "SELECT count(*) FROM memberships") == 2


async def test_concurrent_accepts_respect_the_staff_limit(client, world):
    org_id = await seed_org(world.engine, {"owner": "OWNER"}, tier="enterprise")
    tokens = {}
    for name in ("a", "b", "c", "d", "e"):
        tokens[name] = token_of(await invite(client, org_id, f"{name}@example.com"))
        await seed_user(world.engine, name)
    # Downgraded to Pro (5 members): the owner plus four of the five invitees.
    async with world.engine.begin() as connection:
        await connection.execute(
            text("UPDATE organizations SET subscription_tier = 'pro'")
        )

    responses = await asyncio.gather(
        *(accept(client, token, name) for name, token in tokens.items())
    )

    assert sorted(r.status_code for r in responses) == [200, 200, 200, 200, 409]
    assert await scalar(world.engine, "SELECT count(*) FROM memberships") == 5
