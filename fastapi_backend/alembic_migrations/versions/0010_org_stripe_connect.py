"""Organisation Stripe Connect account and capability flags (KAN-67)

Adds `organizations.stripe_connect_account_id` (unique) and the capability flags
mirrored from Stripe's `account.updated` webhook, plus `stripe_connect_event_at`, the
Stripe `created` time of the last event applied so an older event never overwrites
newer state. Existing rows start with no account and every flag false, which is the
truth: no organisation has onboarded yet.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FLAGS = (
    "connect_charges_enabled",
    "connect_payouts_enabled",
    "connect_details_submitted",
)


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("stripe_connect_account_id", sa.Text(), nullable=True),
    )
    op.create_unique_constraint(
        op.f("uq_organizations_stripe_connect_account_id"),
        "organizations",
        ["stripe_connect_account_id"],
    )
    for flag in FLAGS:
        op.add_column(
            "organizations",
            sa.Column(
                flag, sa.Boolean(), server_default=sa.text("false"), nullable=False
            ),
        )
    op.add_column(
        "organizations",
        sa.Column("stripe_connect_event_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "stripe_connect_event_at")
    for flag in reversed(FLAGS):
        op.drop_column("organizations", flag)
    op.drop_constraint(
        op.f("uq_organizations_stripe_connect_account_id"),
        "organizations",
        type_="unique",
    )
    op.drop_column("organizations", "stripe_connect_account_id")
