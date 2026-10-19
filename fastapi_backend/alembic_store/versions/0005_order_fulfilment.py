"""Manual fulfilment columns on orders (KAN-79)

Store-database table only (the platform tree is untouched). Expand-only: three nullable
columns and two CHECKs, no data rewrite.

* ``tracking_number`` and ``carrier`` are free text the merchant types when shipping an
  order by hand (1 to 100 characters when set). ``fulfilled_at`` is when that happened.
* A ``fulfilled`` order always has a tracking number. The columns stay set when a fulfilled
  order is later refunded. The service writes all three in the one statement that moves the
  status (``fulfil_order`` in ``app/services/store_orders.py``).

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
    op.create_check_constraint(
        "ck_orders_fulfilled_tracking",
        "orders",
        "status <> 'fulfilled' OR tracking_number IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_orders_fulfilled_tracking", "orders", type_="check")
    op.drop_constraint("ck_orders_carrier", "orders", type_="check")
    op.drop_constraint("ck_orders_tracking_number", "orders", type_="check")
    op.drop_column("orders", "fulfilled_at")
    op.drop_column("orders", "carrier")
    op.drop_column("orders", "tracking_number")
