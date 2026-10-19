"""Manual fulfilment columns on orders (KAN-79)

Store-database table only (the platform tree is untouched). Expand-only: three nullable
columns and two CHECKs, no data rewrite.

* ``tracking_number`` and ``carrier`` are free text the merchant types when shipping an
  order by hand (1 to 100 characters when set). ``fulfilled_at`` is when that happened.
* A ``fulfilled`` order always has a tracking number. The columns stay set when a fulfilled
  order is later refunded. The service writes all three in the one statement that moves the
  status (``fulfil_order`` in ``app/services/store_orders.py``).
* ``ck_orders_fulfilled_tracking`` is added NOT VALID: before this revision ``transition_order`` could set
  ``fulfilled`` without a tracking number, so a legacy row would fail the upgrade. It is enforced for every new and
  updated row; validating old rows is left to a later revision once they are backfilled.
* ``ix_orders_created_at`` serves the unfiltered list (newest first, ``id`` as tiebreak).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("tracking_number", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("carrier", sa.String(), nullable=True))
    op.add_column(
        "orders", sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_orders_tracking_number",
        "orders",
        "tracking_number IS NULL OR char_length(tracking_number) BETWEEN 1 AND 100",
    )
    op.create_check_constraint(
        "ck_orders_carrier",
        "orders",
        "carrier IS NULL OR char_length(carrier) BETWEEN 1 AND 100",
    )
    op.execute(
        "ALTER TABLE orders ADD CONSTRAINT ck_orders_fulfilled_tracking "
        "CHECK (status <> 'fulfilled' OR tracking_number IS NOT NULL) NOT VALID"
    )
    op.create_index(
        "ix_orders_created_at",
        "orders",
        [sa.text("created_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_constraint("ck_orders_fulfilled_tracking", "orders", type_="check")
    op.drop_constraint("ck_orders_carrier", "orders", type_="check")
    op.drop_constraint("ck_orders_tracking_number", "orders", type_="check")
    op.drop_column("orders", "fulfilled_at")
    op.drop_column("orders", "carrier")
    op.drop_column("orders", "tracking_number")
