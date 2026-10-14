from typing import Any

from sqlalchemy import DateTime, Table, UniqueConstraint

import app.models.platform  # noqa: F401  (registers the tables)
from app.core.base import Base
from app.models.platform import MembershipRole, StoreStatus

EXPECTED_TABLES = {
    # boilerplate (Prisma) models
    "users",
    "user_settings",
    "login_history",
    "notifications",
    "admin_users",
    "audit_logs",
    "seo_meta",
    "url_redirects",
    "app_settings",
    "feature_flags",
    "email_templates",
    # platform additions (ADR-005, ADR-010)
    "organizations",
    "memberships",
    "invitations",
    "stores",
    # billing webhook (KAN-44)
    "stripe_events",
}

BILLING_COLUMNS = {
    "stripe_customer_id",
    "stripe_subscription_id",
    "stripe_price_id",
    "stripe_current_period_end",
    "subscription_tier",
    "subscription_status",
    "platform_fee_bps",
}


def table(name: str) -> Table:
    return Base.metadata.tables[name]


def column_sets(items: Any) -> set[tuple[str, ...]]:
    return {tuple(column.name for column in item.columns) for item in items}


def test_metadata_contains_exactly_the_platform_tables():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_billing_lives_on_organizations_not_users():
    assert BILLING_COLUMNS <= set(table("organizations").columns.keys())
    assert not BILLING_COLUMNS & set(table("users").columns.keys())


def test_platform_fee_defaults_to_zero():
    default = table("organizations").columns["platform_fee_bps"].server_default

    assert default is not None
    assert str(default.arg) == "0"  # type: ignore[attr-defined]


def test_store_registry_holds_a_reference_and_no_credentials():
    stores = table("stores")
    names = set(stores.columns.keys())

    assert {"organization_id", "slug", "status", "schema_version", "database_ref"} <= (
        names
    )
    assert stores.columns["database_ref"].nullable
    assert stores.columns["slug"].unique
    assert not {n for n in names if "password" in n or "secret" in n or "url" in n}


def test_membership_is_unique_per_organization_and_user():
    uniques = [
        c for c in table("memberships").constraints if isinstance(c, UniqueConstraint)
    ]

    assert ("organization_id", "user_id") in column_sets(uniques)


def test_roles_and_store_statuses_are_the_decided_values():
    assert [role.value for role in MembershipRole] == ["OWNER", "ADMIN", "STAFF"]
    assert StoreStatus.PROVISIONING.value == "PROVISIONING"


def test_audit_logs_index_organization_by_time():
    audit = table("audit_logs")

    assert audit.columns["organization_id"].nullable
    assert ("organization_id", "created_at") in column_sets(audit.indexes)


def test_primary_keys_are_generated_string_ids():
    for name, tbl in Base.metadata.tables.items():
        key = tbl.primary_key.columns["id"]
        assert key.type.python_type is str, name
        assert key.default is not None, name


def test_every_datetime_column_is_timezone_aware():
    for name, tbl in Base.metadata.tables.items():
        for column in tbl.columns:
            if isinstance(column.type, DateTime):
                assert column.type.timezone, f"{name}.{column.name}"


def test_constraints_follow_the_naming_convention():
    assert table("memberships").primary_key.name == "pk_memberships"
