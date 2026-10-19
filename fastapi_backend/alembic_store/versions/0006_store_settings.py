"""Store settings: shipping and tax (KAN-82, KAN-83)

Store-database table only (the platform tree is untouched). Expand-only: one new table with
one row.

* ``store_settings`` is a singleton: the primary key is a boolean that the check forces to
  true, so a second row cannot exist. The row is inserted here with defaults (no shipping
  charge, no threshold, no tax, prices exclude tax), so reads never meet a missing row.
* Money is integer minor units like the catalogue. ``shipping_flat_rate_minor`` is charged
  per order; ``free_shipping_threshold_minor`` (null = never free) waives it when the item
  subtotal reaches the threshold.
* ``tax_rate_bps`` is basis points (2000 = 20%), capped at 10000 (100%), a subset of what
  ``order_items.tax_rate_bps`` accepts. ``prices_include_tax`` says whether catalogue
  prices already contain the tax.
* Amounts are capped at 100 000 000 000 minor units so a typo cannot overflow later sums.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19
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
    op.create_table(
        "store_settings",
        sa.Column("id", sa.Boolean(), primary_key=True, server_default=sa.true()),
        sa.Column(
            "shipping_flat_rate_minor",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("free_shipping_threshold_minor", sa.BigInteger(), nullable=True),
        sa.Column("tax_rate_bps", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "prices_include_tax",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id", name="ck_store_settings_singleton"),
        sa.CheckConstraint(
            "shipping_flat_rate_minor BETWEEN 0 AND 100000000000",
            name="ck_store_settings_shipping_flat_rate_minor",
        ),
        sa.CheckConstraint(
            "free_shipping_threshold_minor IS NULL"
            " OR free_shipping_threshold_minor BETWEEN 1 AND 100000000000",
            name="ck_store_settings_free_shipping_threshold_minor",
        ),
        sa.CheckConstraint(
            "tax_rate_bps BETWEEN 0 AND 10000", name="ck_store_settings_tax_rate_bps"
        ),
    )
    op.execute(
        "INSERT INTO store_settings (id) VALUES (true) ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("store_settings")
