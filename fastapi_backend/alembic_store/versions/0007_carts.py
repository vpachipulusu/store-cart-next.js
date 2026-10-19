"""Shopper carts (KAN-76)

Store-database tables only (the platform tree is untouched). Expand-only: new tables.

* ``carts`` is keyed by the SHA-256 of an opaque token. The token itself lives only in the
  shopper's store-scoped cookie (Next.js sets it), so a database read never yields a usable
  token. ``expires_at`` is pushed forward on every write; an expired cart is treated as
  absent and purged on the next write.
* ``cart_items`` holds a variant and a quantity only. Names, prices and stock are never
  stored: they are read from the catalogue on every cart request. Deleting a variant
  removes it from every cart. A cart holds a variant once; quantity is 1 to 99.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "carts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
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
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name="ck_carts_token_hash_format"
        ),
        sa.UniqueConstraint("token_hash", name="uq_carts_token_hash"),
    )
    op.create_index("ix_carts_expires_at", "carts", ["expires_at"])

    op.create_table(
        "cart_items",
        sa.Column(
            "cart_id",
            sa.String(),
            sa.ForeignKey("carts.id", ondelete="CASCADE", name="fk_cart_items_cart"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            sa.String(),
            sa.ForeignKey(
                "variants.id", ondelete="CASCADE", name="fk_cart_items_variant"
            ),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("cart_id", "variant_id"),
        sa.CheckConstraint("quantity BETWEEN 1 AND 99", name="ck_cart_items_quantity"),
    )
    op.create_index("ix_cart_items_variant_id", "cart_items", ["variant_id"])


def downgrade() -> None:
    """Drops both tables, so every open cart is lost."""
    op.drop_table("cart_items")
    op.drop_table("carts")
