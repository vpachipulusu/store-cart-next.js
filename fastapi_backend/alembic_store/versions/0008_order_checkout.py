"""Checkout columns on orders (KAN-68)

Store-database table only (the platform tree is untouched). Expand-only: new columns with
defaults or nullable, one unique index and a replaced CHECK; no data rewrite. Code from before
this revision keeps working: it inserts no shipping (default 0) and tax added on top (default
false), which the new CHECK accepts.

* ``shipping_minor`` and ``prices_include_tax`` record how checkout priced the order with the
  store settings (``store_totals.compute_totals``). The total rule becomes
  ``total = subtotal + shipping + (tax unless prices include it)``. The new CHECK is added
  NOT VALID and then validated, so the scan of existing rows does not block writes.
* ``stripe_checkout_session_id`` is the Checkout Session created for the order on the
  merchant's connected account. Unique: the Connect webhook confirms by it, so a session can
  pay one order only, and a redelivered event finds the order already paid.
* ``stripe_payment_intent_id`` and ``paid_at`` are set when the webhook confirms payment.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TOTAL_RULE = (
    "total_minor = subtotal_minor + shipping_minor"
    " + CASE WHEN prices_include_tax THEN 0 ELSE tax_minor END"
)


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "shipping_minor", sa.BigInteger(), server_default="0", nullable=False
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "prices_include_tax",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "orders", sa.Column("stripe_checkout_session_id", sa.String(), nullable=True)
    )
    op.add_column(
        "orders", sa.Column("stripe_payment_intent_id", sa.String(), nullable=True)
    )
    op.add_column(
        "orders", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_orders_shipping_minor", "orders", "shipping_minor >= 0"
    )
    op.create_check_constraint(
        "ck_orders_stripe_checkout_session_id",
        "orders",
        "stripe_checkout_session_id IS NULL"
        " OR char_length(stripe_checkout_session_id) BETWEEN 1 AND 255",
    )
    op.create_check_constraint(
        "ck_orders_stripe_payment_intent_id",
        "orders",
        "stripe_payment_intent_id IS NULL"
        " OR char_length(stripe_payment_intent_id) BETWEEN 1 AND 255",
    )
    op.create_index(
        "uq_orders_stripe_checkout_session_id",
        "orders",
        ["stripe_checkout_session_id"],
        unique=True,
    )
    op.drop_constraint("ck_orders_total_minor", "orders", type_="check")
    op.execute(
        "ALTER TABLE orders ADD CONSTRAINT ck_orders_total_minor"
        f" CHECK ({NEW_TOTAL_RULE}) NOT VALID"
    )
    op.execute("ALTER TABLE orders VALIDATE CONSTRAINT ck_orders_total_minor")


def downgrade() -> None:
    """Drops the checkout columns.

    Fails if an order has shipping or included tax, since it would break the old total rule.
    """
    op.drop_constraint("ck_orders_total_minor", "orders", type_="check")
    op.create_check_constraint(
        "ck_orders_total_minor", "orders", "total_minor = subtotal_minor + tax_minor"
    )
    op.drop_index("uq_orders_stripe_checkout_session_id", table_name="orders")
    op.drop_constraint("ck_orders_stripe_payment_intent_id", "orders", type_="check")
    op.drop_constraint("ck_orders_stripe_checkout_session_id", "orders", type_="check")
    op.drop_constraint("ck_orders_shipping_minor", "orders", type_="check")
    op.drop_column("orders", "paid_at")
    op.drop_column("orders", "stripe_payment_intent_id")
    op.drop_column("orders", "stripe_checkout_session_id")
    op.drop_column("orders", "prices_include_tax")
    op.drop_column("orders", "shipping_minor")
