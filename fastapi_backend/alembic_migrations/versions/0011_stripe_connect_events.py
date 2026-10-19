"""Stripe Connect webhook events (KAN-69)

Adds `stripe_connect_events`: one row per applied Stripe Connect event, unique on the
Stripe event id (the idempotency key), with the connected account and the organisation
and store the event was routed to. Kept apart from the Billing `stripe_events` ledger:
a separate endpoint, signing secret and history. Rows go with their organisation
(cascade); a deleted store leaves the row with a null store.

Size assumption: a new, empty table, so the index builds take no meaningful lock.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stripe_connect_events",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("stripe_event_id", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("stripe_account_id", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Text(), nullable=False),
        sa.Column("store_id", sa.Text(), nullable=True),
        sa.Column("stripe_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_stripe_connect_events_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_stripe_connect_events_store_id_stores"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stripe_connect_events")),
        sa.UniqueConstraint(
            "stripe_event_id", name=op.f("uq_stripe_connect_events_stripe_event_id")
        ),
    )
    op.create_index(
        op.f("ix_stripe_connect_events_organization_id"),
        "stripe_connect_events",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_stripe_connect_events_store_id"),
        "stripe_connect_events",
        ["store_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_stripe_connect_events_store_id"), table_name="stripe_connect_events"
    )
    op.drop_index(
        op.f("ix_stripe_connect_events_organization_id"),
        table_name="stripe_connect_events",
    )
    op.drop_table("stripe_connect_events")
