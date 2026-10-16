"""Shared fixtures and helpers for the admin subscriptions e2e tests (KAN-48).

End to end on a real Postgres: the admin subscriptions routes, dependency chain and audit trail.

Same contract as ``test_admin_users_e2e.py``: runs only when ``TEST_DATABASE_URL`` points
at a throwaway local database whose name ends in "_test", and rebuilds its schema with
the real Alembic migrations. Only Firebase (identity from an ``X-Test-Uid`` header) and
Stripe (``FakeStripeAdmin``, never the network) are replaced. ``require_admin``, the audit
service, the repositories and the transaction handling are the production code.
"""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.ids import new_id

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND_ROOT = Path(__file__).resolve().parents[3]
KEY = "test-only-internal-service-key-not-for-deployment"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
MANAGER = [
    "subscriptions.read",
    "subscriptions.update",
    "subscriptions.refund",
    "subscriptions.grant",
]
BASE = "/v1/admin/subscriptions"


async def seed_user(
    engine: AsyncEngine,
    name: str,
    role: str | None = None,
    permissions: list[str] | None = None,
) -> str:
    """Insert a user (firebase uid ``fb-<name>``) and, with a role, its admin grant."""
    user_id = new_id()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (id, firebase_uid, email, email_verified, "
                "display_name) VALUES (:id, :uid, :email, true, :name)"
            ),
            {
                "id": user_id,
                "uid": f"fb-{name}",
                "email": f"{name}@example.com",
                "name": name.title(),
            },
        )
        if role:
            await connection.execute(
                text(
                    "INSERT INTO admin_users (id, user_id, role, permissions) "
                    "VALUES (:id, :user_id, :role, CAST(:perms AS jsonb))"
                ),
                {
                    "id": new_id(),
                    "user_id": user_id,
                    "role": role,
                    "perms": json.dumps(permissions or []),
                },
            )
    return user_id


async def seed_org(engine: AsyncEngine, **columns: Any) -> str:
    """Insert an organisation; keyword arguments are column values."""
    org_id = columns.pop("id", None) or new_id()
    values = {"id": org_id, "name": "Acme", "slug": f"acme-{org_id.lower()}", **columns}
    names = ", ".join(values)
    params = ", ".join(f":{name}" for name in values)
    async with engine.begin() as connection:
        await connection.execute(
            text(f"INSERT INTO organizations ({names}) VALUES ({params})"), values
        )
    return org_id


def paying(**columns: Any) -> dict[str, Any]:
    return {
        "stripe_customer_id": "cus_1",
        "stripe_subscription_id": "sub_1",
        "stripe_price_id": "price_pro_m",
        "subscription_tier": "pro",
        "subscription_status": "active",
        **columns,
    }


async def rows(engine: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with engine.connect() as connection:
        return list((await connection.execute(text(sql), params)).all())


async def audit_rows(engine: AsyncEngine, action: str | None = None) -> list[Any]:
    sql = (
        "SELECT user_id, action, resource, resource_id, organization_id, metadata "
        "FROM audit_logs"
    )
    if action:
        return await rows(
            engine, sql + " WHERE action = :a ORDER BY created_at", a=action
        )
    return await rows(engine, sql + " ORDER BY created_at")


async def org_columns(engine: AsyncEngine, org_id: str) -> Any:
    found = await rows(
        engine,
        "SELECT subscription_tier, subscription_status, stripe_subscription_id, "
        "stripe_cancel_at_period_end, granted_plan, granted_until "
        "FROM organizations WHERE id = :id",
        id=org_id,
    )
    return found[0]


def as_user(name: str) -> dict[str, str]:
    return {"X-Test-Uid": f"fb-{name}", "User-Agent": "e2e-agent"}


def keyed(name: str, key: str = "key-aaaa-0001") -> dict[str, str]:
    return {**as_user(name), "Idempotency-Key": key}


def in_days(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


GRANT_BODY = {"plan": "pro", "expires_at": "2099-01-01T00:00:00Z"}
ROUTES = [
    ("GET", BASE, None),
    ("GET", f"{BASE}/org1", None),
    ("POST", f"{BASE}/org1/cancel", {}),
    ("POST", f"{BASE}/org1/refunds", {"charge_id": "ch_1"}),
    ("PUT", f"{BASE}/org1/grant", GRANT_BODY),
    ("DELETE", f"{BASE}/org1/grant", None),
]


def refund_url(org_id: str) -> str:
    return f"{BASE}/{org_id}/refunds"


def grant_url(org_id: str) -> str:
    return f"{BASE}/{org_id}/grant"


async def seed_owner(engine: AsyncEngine, org_id: str, name: str = "owner") -> None:
    user_id = await seed_user(engine, name)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO memberships (id, organization_id, user_id, role) "
                "VALUES (:id, :org, :user, 'OWNER')"
            ),
            {"id": new_id(), "org": org_id, "user": user_id},
        )
