"""Allow the FAILED store status (KAN-56)

The provisioning job sets `stores.status` to FAILED when a step exhausts its retries.
Only the CHECK constraint changes; no row is rewritten.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-17
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_stores_status_valid"


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), "stores", type_="check")
    op.create_check_constraint(
        op.f(CONSTRAINT),
        "stores",
        "status IN ('PROVISIONING', 'ACTIVE', 'FAILED', 'SUSPENDED', 'ARCHIVED')",
    )


def downgrade() -> None:
    # A FAILED store cannot satisfy the old constraint: park it as ARCHIVED.
    op.execute("UPDATE stores SET status = 'ARCHIVED' WHERE status = 'FAILED'")
    op.drop_constraint(op.f(CONSTRAINT), "stores", type_="check")
    op.create_check_constraint(
        op.f(CONSTRAINT),
        "stores",
        "status IN ('PROVISIONING', 'ACTIVE', 'SUSPENDED', 'ARCHIVED')",
    )
