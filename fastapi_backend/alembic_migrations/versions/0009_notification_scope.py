"""Scope notifications to an organisation or store (KAN-40)

Adds nullable `notifications.organization_id` and `notifications.store_id` (both
cascade with their parent, so a deleted store or organisation takes its notifications
with it), a CHECK that a store scope always names its organisation, and the indexes
behind the list order and the scope filters. Existing rows stay personal (both null).

Size assumption: plain (non-CONCURRENT) index builds block writes to `notifications`.
That is acceptable while the table is small (pre-launch, nothing writes it yet).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications", sa.Column("organization_id", sa.Text(), nullable=True)
    )
    op.add_column("notifications", sa.Column("store_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f("fk_notifications_organization_id_organizations"),
        "notifications",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_notifications_store_id_stores"),
        "notifications",
        "stores",
        ["store_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        op.f("ck_notifications_store_requires_organization"),
        "notifications",
        "store_id IS NULL OR organization_id IS NOT NULL",
    )
    op.create_index(
        "ix_notifications_user_id_created_at",
        "notifications",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_notifications_user_id_organization_id",
        "notifications",
        ["user_id", "organization_id"],
    )
    op.create_index(
        "ix_notifications_user_id_store_id", "notifications", ["user_id", "store_id"]
    )
    # The cascading foreign keys look rows up by these columns alone.
    op.create_index(
        "ix_notifications_organization_id",
        "notifications",
        ["organization_id"],
        postgresql_where=sa.text("organization_id IS NOT NULL"),
    )
    op.create_index(
        "ix_notifications_store_id",
        "notifications",
        ["store_id"],
        postgresql_where=sa.text("store_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_store_id", table_name="notifications")
    op.drop_index("ix_notifications_organization_id", table_name="notifications")
    op.drop_index("ix_notifications_user_id_store_id", table_name="notifications")
    op.drop_index(
        "ix_notifications_user_id_organization_id", table_name="notifications"
    )
    op.drop_index("ix_notifications_user_id_created_at", table_name="notifications")
    op.drop_constraint(
        op.f("ck_notifications_store_requires_organization"),
        "notifications",
        type_="check",
    )
    op.drop_constraint(
        op.f("fk_notifications_store_id_stores"), "notifications", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_notifications_organization_id_organizations"),
        "notifications",
        type_="foreignkey",
    )
    op.drop_column("notifications", "store_id")
    op.drop_column("notifications", "organization_id")
