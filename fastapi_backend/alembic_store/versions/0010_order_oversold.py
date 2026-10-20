"""Oversold flag on orders (KAN-72)

Store-database table only (the platform tree is untouched). Expand-only: one ``NOT NULL``
column with a constant default and a partial index. Code from before this revision keeps
working: it never writes the column, and the default fills it.

* ``orders.oversold`` is set when the order was paid but the stock could not cover every
  line (a concurrent order took the last unit first). The order stays ``paid``: the shopper
  has been charged, so the merchant resolves it (fulfil late, or refund). Existing orders get
  ``false``: stock was never decremented before this revision, so none of them is oversold
  by this rule. A constant default is a metadata-only change on PostgreSQL 11 and later.
* ``ix_orders_oversold`` lists the orders that need attention without scanning the table.
  It is partial, so it stays tiny.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("oversold", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index(
        "ix_orders_oversold",
        "orders",
        ["id"],
        postgresql_where=sa.text("oversold"),
    )


def downgrade() -> None:
    """Drops the flag; no order is lost, but which orders were oversold is forgotten."""
    op.drop_index("ix_orders_oversold", table_name="orders")
    op.drop_column("orders", "oversold")
