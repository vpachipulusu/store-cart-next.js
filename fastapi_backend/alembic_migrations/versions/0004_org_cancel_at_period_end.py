"""Organisation cancel-at-period-end flag (KAN-182)

Adds `organizations.stripe_cancel_at_period_end`, written only by the Stripe webhook
so the billing page can show whether the subscription will renew.

Backfill: Stripe is the source of truth and a migration must not call it, so existing
rows start at false. An organisation subscribed before this migration that has already
scheduled cancellation shows the wrong value until its next subscription webhook; see
"Backfill" in docs/developer/backend-org-billing.md for the one-off remedy.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "stripe_cancel_at_period_end",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "stripe_cancel_at_period_end")
