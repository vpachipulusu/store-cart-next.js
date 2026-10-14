"""Stripe billing webhook (KAN-44)

Adds `stripe_events` (one row per applied Stripe event, unique on the Stripe event
id, the idempotency key) and `organizations.stripe_subscription_event_at` (the
Stripe `created` time of the last subscription event applied, so an older event
arriving late is ignored).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stripe_events",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("stripe_event_id", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("stripe_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stripe_events")),
        sa.UniqueConstraint(
            "stripe_event_id", name=op.f("uq_stripe_events_stripe_event_id")
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "stripe_subscription_event_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "stripe_subscription_event_at")
    op.drop_table("stripe_events")
