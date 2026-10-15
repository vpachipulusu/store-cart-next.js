"""Complimentary plan grant on organisations (KAN-48)

Adds `organizations.granted_plan` and `granted_until`, written only by the platform
admin API. They are separate from the Stripe-backed `subscription_tier`/status so the
Stripe webhook (the single writer of those) can never overwrite or contradict a grant.
Both columns are NULL together or set together, and the plan must be a paid one.
Existing rows have no grant.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("granted_plan", sa.Text(), nullable=True))
    op.add_column(
        "organizations",
        sa.Column("granted_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "granted_plan_valid", "organizations", "granted_plan IN ('pro', 'enterprise')"
    )
    op.create_check_constraint(
        "grant_complete",
        "organizations",
        "(granted_plan IS NULL) = (granted_until IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("grant_complete", "organizations", type_="check")
    op.drop_constraint("granted_plan_valid", "organizations", type_="check")
    op.drop_column("organizations", "granted_until")
    op.drop_column("organizations", "granted_plan")
