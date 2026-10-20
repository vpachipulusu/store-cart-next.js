"""Order refunds and the stock a paid order took (KAN-80)

Store-database tables only (the platform tree is untouched). Expand-only: two new tables and
two defaulted columns; no data rewrite. Code from before this revision keeps working: it never
writes the new columns, and the defaults fill them.

* ``order_items.stock_taken`` is how many units ``take_paid_stock`` (KAN-72) took from the
  variant when the order was paid: the whole line, or 0 when stock could not cover it (the
  order is then ``oversold``) or the variant was deleted. A refund restocks at most this much,
  so a unit that was never taken is never added back. Existing lines get 0: whether an old
  order took stock is unknown (orders paid before 0010 never did), so they are never restocked
  by a refund.
* ``order_items.restocked_quantity`` is how much of ``stock_taken`` refunds have returned so
  far (never above it), so restocking is bounded per line however many refunds there are.
* ``order_refunds`` is one row per refund requested through the connected account. ``pending``
  rows count against what can still be refunded until Stripe settles them (``succeeded``, or
  ``failed``, which releases the amount). ``stripe_refund_id`` is unique: one Stripe refund
  settles one row. ``restock`` is the merchant's per-refund choice (default off) and
  ``restocked_at`` marks that the restock was applied, in the same transaction that settled it.
* ``order_refunds.client_key`` is the caller's ``Idempotency-Key`` (unique per order): a retried
  request returns the refund it already made. ``order_id`` and ``order_item_id`` references
  are ``RESTRICT``: a financial record is never removed by deleting its order or line.
* ``order_refund_items`` holds the lines (order item and quantity) a refund covers; a full
  refund lists every remaining line.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-20
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
    op.add_column(
        "order_items",
        sa.Column("stock_taken", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "order_items",
        sa.Column(
            "restocked_quantity", sa.Integer(), server_default="0", nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_order_items_stock_taken",
        "order_items",
        "stock_taken BETWEEN 0 AND quantity",
    )
    op.create_check_constraint(
        "ck_order_items_restocked_quantity",
        "order_items",
        "restocked_quantity BETWEEN 0 AND stock_taken",
    )

    op.create_table(
        "order_refunds",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "order_id",
            sa.String(),
            sa.ForeignKey(
                "orders.id", ondelete="RESTRICT", name="fk_order_refunds_order"
            ),
            nullable=False,
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("restock", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("restocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stripe_refund_id", sa.String(), nullable=True),
        sa.Column("client_key", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount_minor > 0", name="ck_order_refunds_amount_minor"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_order_refunds_currency"),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_order_refunds_status",
        ),
        sa.CheckConstraint(
            "stripe_refund_id IS NULL"
            " OR char_length(stripe_refund_id) BETWEEN 1 AND 255",
            name="ck_order_refunds_stripe_refund_id",
        ),
        sa.CheckConstraint(
            "client_key IS NULL OR char_length(client_key) BETWEEN 1 AND 64",
            name="ck_order_refunds_client_key",
        ),
        sa.CheckConstraint(
            "restocked_at IS NULL OR (restock AND status = 'succeeded')",
            name="ck_order_refunds_restocked_at",
        ),
    )
    # The foreign key's index, and the per-order refund list.
    op.create_index("ix_order_refunds_order_id", "order_refunds", ["order_id"])
    op.create_index(
        "uq_order_refunds_stripe_refund_id",
        "order_refunds",
        ["stripe_refund_id"],
        unique=True,
        postgresql_where=sa.text("stripe_refund_id IS NOT NULL"),
    )
    # A client retry with the same key finds its refund instead of making another.
    op.create_index(
        "uq_order_refunds_order_client_key",
        "order_refunds",
        ["order_id", "client_key"],
        unique=True,
        postgresql_where=sa.text("client_key IS NOT NULL"),
    )

    op.create_table(
        "order_refund_items",
        sa.Column(
            "refund_id",
            sa.String(),
            sa.ForeignKey(
                "order_refunds.id",
                ondelete="CASCADE",
                name="fk_order_refund_items_refund",
            ),
            nullable=False,
        ),
        sa.Column(
            "order_item_id",
            sa.String(),
            sa.ForeignKey(
                "order_items.id", ondelete="RESTRICT", name="fk_order_refund_items_item"
            ),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("refund_id", "order_item_id"),
        sa.CheckConstraint(
            "quantity BETWEEN 1 AND 10000", name="ck_order_refund_items_quantity"
        ),
    )
    op.create_index(
        "ix_order_refund_items_order_item_id", "order_refund_items", ["order_item_id"]
    )


def downgrade() -> None:
    """Drops the refund records and the stock bookkeeping; orders and stock are untouched.

    Which refunds were requested, and how much stock they returned, is forgotten here: the
    money itself lives at Stripe.
    """
    op.drop_table("order_refund_items")
    op.drop_table("order_refunds")
    op.drop_constraint(
        "ck_order_items_restocked_quantity", "order_items", type_="check"
    )
    op.drop_constraint("ck_order_items_stock_taken", "order_items", type_="check")
    op.drop_column("order_items", "restocked_quantity")
    op.drop_column("order_items", "stock_taken")
