"""Orders and order items with purchase-time snapshots (KAN-78)

Store-database tables only (the platform tree is untouched). Expand-only: new tables.

* Money is integer minor units (``*_minor``, bigint) like the catalogue. Unlike the catalogue,
  an order stores its ``currency`` (ISO 4217 code, upper case): the store setting can change,
  a paid order must not. ``total_minor`` is always ``subtotal_minor + tax_minor``.
* ``order_items`` snapshot what was sold: ``product_name``, ``sku``, ``variant_label`` (the
  chosen option values, e.g. "Large / Red"), ``unit_price_minor``, ``tax_rate_bps`` (basis
  points, 2000 = 20%) and ``tax_minor``. Nothing is read back from the catalogue after
  purchase, so renaming a product or changing a price never changes an order.
* ``product_id`` and ``variant_id`` are only a link back to the catalogue. They are nullable
  and ``ON DELETE SET NULL``: deleting a product or variant keeps the order line intact.
  Deleting an order removes its items.
* ``status`` is ``pending`` (default), ``paid``, ``fulfilled``, ``cancelled`` or ``refunded``.
  Which moves are allowed (pending > paid > fulfilled, pending/paid > cancelled,
  paid/fulfilled > refunded) is a service rule (``app/services/store_orders.py``); the check
  here only limits the set of values.
* ``orders.updated_at`` has only a server default; the writing service sets it on update.
  ``order_items`` are immutable snapshots and have ``created_at`` only.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[datetime]]:
    return [
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        )
        for name in ("created_at", "updated_at")
    ]


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("subtotal_minor", sa.BigInteger(), nullable=False),
        sa.Column("tax_minor", sa.BigInteger(), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'paid', 'fulfilled', 'cancelled', 'refunded')",
            name="ck_orders_status",
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_orders_currency"),
        sa.CheckConstraint("subtotal_minor >= 0", name="ck_orders_subtotal_minor"),
        sa.CheckConstraint("tax_minor >= 0", name="ck_orders_tax_minor"),
        sa.CheckConstraint(
            "total_minor = subtotal_minor + tax_minor", name="ck_orders_total_minor"
        ),
    )
    # Lists orders by status, newest first.
    op.create_index("ix_orders_status_created_at", "orders", ["status", "created_at"])

    op.create_table(
        "order_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "order_id",
            sa.String(),
            sa.ForeignKey("orders.id", ondelete="CASCADE", name="fk_order_items_order"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.String(),
            sa.ForeignKey(
                "products.id", ondelete="SET NULL", name="fk_order_items_product"
            ),
            nullable=True,
        ),
        sa.Column(
            "variant_id",
            sa.String(),
            sa.ForeignKey(
                "variants.id", ondelete="SET NULL", name="fk_order_items_variant"
            ),
            nullable=True,
        ),
        sa.Column("product_name", sa.String(), nullable=False),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("variant_label", sa.String(), nullable=True),
        sa.Column("unit_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("tax_rate_bps", sa.Integer(), nullable=False),
        sa.Column("tax_minor", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            r"product_name ~ '\S' AND char_length(product_name) <= 255",
            name="ck_order_items_product_name",
        ),
        sa.CheckConstraint(
            "char_length(sku) BETWEEN 1 AND 100", name="ck_order_items_sku"
        ),
        sa.CheckConstraint(
            "variant_label IS NULL OR char_length(variant_label) <= 255",
            name="ck_order_items_variant_label",
        ),
        sa.CheckConstraint(
            "unit_price_minor >= 0", name="ck_order_items_unit_price_minor"
        ),
        sa.CheckConstraint(
            "quantity BETWEEN 1 AND 10000", name="ck_order_items_quantity"
        ),
        sa.CheckConstraint(
            "tax_rate_bps BETWEEN 0 AND 100000", name="ck_order_items_tax_rate_bps"
        ),
        sa.CheckConstraint("tax_minor >= 0", name="ck_order_items_tax_minor"),
    )
    # One line per variant and order. Partial: lines whose variant was deleted (NULL) are
    # not constrained, so it cannot serve the order_id foreign key; that needs the plain
    # index below.
    op.create_index(
        "uq_order_items_order_variant",
        "order_items",
        ["order_id", "variant_id"],
        unique=True,
        postgresql_where=sa.text("variant_id IS NOT NULL"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    # The SET NULL foreign keys scan these when a product or variant is deleted.
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])
    op.create_index("ix_order_items_variant_id", "order_items", ["variant_id"])


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")
