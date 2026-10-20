"""One open checkout order per cart, with an expiry (KAN-256)

Store-database table only (the platform tree is untouched). Expand-only: four nullable
columns, three partial indexes and one backfill of ``checkout_expires_at``. Code from before
this revision keeps working: it inserts none of the new columns, and a ``NULL`` cart id is
outside the unique index.

* ``cart_id`` is the cart the order was started from. A partial unique index on it where the
  order is ``pending`` keeps one open checkout per cart in the database itself. The foreign
  key is ``ON DELETE SET NULL`` so purging an expired cart never removes an order.
* ``ix_orders_cart_id`` serves the foreign key: deleting a cart sets ``cart_id`` to NULL on
  its orders, which needs to find them (the unique index covers pending orders only).
* ``checkout_fingerprint`` identifies what the open order was priced and sent for (lines,
  totals, return URLs): an unchanged cart reuses the order, a changed one replaces it.
* ``stripe_checkout_url`` is the Stripe-hosted page of the order's session, so a repeated
  start can return it without another Stripe call.
* ``checkout_expires_at`` is when the session stops being payable; the expiry sweep cancels
  pending orders past it. Existing pending orders get ``created_at + 24 hours`` (Stripe's
  default session life, which is what their sessions have), so the sweep can never cancel an
  order whose session is still payable. Store tables are small; the backfill and the index
  builds hold short locks.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "cart_id",
            sa.String(),
            sa.ForeignKey("carts.id", ondelete="SET NULL", name="fk_orders_cart"),
            nullable=True,
        ),
    )
    op.add_column(
        "orders", sa.Column("checkout_fingerprint", sa.String(64), nullable=True)
    )
    op.add_column("orders", sa.Column("stripe_checkout_url", sa.Text(), nullable=True))
    op.add_column(
        "orders",
        sa.Column("checkout_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_orders_stripe_checkout_url",
        "orders",
        "stripe_checkout_url IS NULL"
        " OR (stripe_checkout_url LIKE 'https://%'"
        " AND char_length(stripe_checkout_url) <= 2048)",
    )
    op.execute(
        "UPDATE orders SET checkout_expires_at = created_at + interval '24 hours'"
        " WHERE status = 'pending'"
    )
    op.create_index(
        "uq_orders_open_checkout_per_cart",
        "orders",
        ["cart_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending' AND cart_id IS NOT NULL"),
    )
    op.create_index(
        "ix_orders_cart_id",
        "orders",
        ["cart_id"],
        postgresql_where=sa.text("cart_id IS NOT NULL"),
    )
    op.create_index(
        "ix_orders_pending_checkout_expires_at",
        "orders",
        ["checkout_expires_at"],
        postgresql_where=sa.text(
            "status = 'pending' AND checkout_expires_at IS NOT NULL"
        ),
    )


def downgrade() -> None:
    """Drops the columns; no order is lost, but the cart link and expiry of open orders go."""
    op.drop_index("ix_orders_pending_checkout_expires_at", table_name="orders")
    op.drop_index("ix_orders_cart_id", table_name="orders")
    op.drop_index("uq_orders_open_checkout_per_cart", table_name="orders")
    op.drop_constraint("ck_orders_stripe_checkout_url", "orders", type_="check")
    op.drop_column("orders", "checkout_expires_at")
    op.drop_column("orders", "stripe_checkout_url")
    op.drop_column("orders", "checkout_fingerprint")
    op.drop_column("orders", "cart_id")
