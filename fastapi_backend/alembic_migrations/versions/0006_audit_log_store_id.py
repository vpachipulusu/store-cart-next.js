"""Tenant-aware audit log (KAN-49)

Adds `audit_logs.store_id` (no foreign key, like the other ids: rows outlive stores)
and the indexes behind the admin list filters: store (with newest-first order) and
plain newest-first. User, action and organisation indexes already exist.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("store_id", sa.Text(), nullable=True))
    # Earlier store rows kept the store id in resource_id; make them filterable.
    op.execute(
        "UPDATE audit_logs SET store_id = resource_id "
        "WHERE resource = 'store' AND resource_id IS NOT NULL"
    )
    op.create_index(
        "ix_audit_logs_store_id_created_at", "audit_logs", ["store_id", "created_at"]
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_store_id_created_at", table_name="audit_logs")
    op.drop_column("audit_logs", "store_id")
