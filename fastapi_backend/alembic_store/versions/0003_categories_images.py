"""Nested categories, product-category links and ordered product images (KAN-71)

Store-database tables only (the platform tree is untouched). Expand-only: new tables.

* ``categories`` is an adjacency list: ``parent_id`` points at the parent (null for a root)
  and ``position`` orders siblings (ties break by id in the reader). Deleting a category
  that still has children is rejected (``RESTRICT``) so a subtree is never lost silently.
  That the parent chain has no cycle and a depth limit are service rules.
* ``categories.slug`` is unique per store, lower-case hyphenated, like ``products.slug``.
* ``product_categories`` links a product to many categories; deleting either side removes
  only the links.
* ``product_images`` holds the R2 object key (``stores/{store_id}/{id}.{ext}``, built by
  ``MediaUploadService``; the bucket's public base URL is configuration, not data).
  ``position`` is unique per product, ``DEFERRABLE INITIALLY DEFERRED`` so a reorder (a swap)
  can run in one transaction. Deleting the product deletes the rows; deleting the R2 objects
  is a service job.
* ``updated_at`` has only a server default; the writing service sets it on update.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
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
        "categories",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "parent_id",
            sa.String(),
            sa.ForeignKey(
                "categories.id", ondelete="RESTRICT", name="fk_categories_parent"
            ),
            nullable=True,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            r"name ~ '\S' AND char_length(name) <= 255", name="ck_categories_name"
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) <= 200",
            name="ck_categories_slug_format",
        ),
        sa.CheckConstraint("position >= 0", name="ck_categories_position"),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name="ck_categories_not_own_parent"
        ),
        sa.UniqueConstraint("slug", name="uq_categories_slug"),
    )
    # Lists the children of a parent in order; also covers the parent foreign key.
    op.create_index(
        "ix_categories_parent_position", "categories", ["parent_id", "position"]
    )

    op.create_table(
        "product_categories",
        sa.Column("product_id", sa.String(), nullable=False),
        sa.Column("category_id", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("product_id", "category_id"),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_product_categories_product",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name="fk_product_categories_category",
            ondelete="CASCADE",
        ),
    )
    # The primary key covers product_id; this serves "products in a category".
    op.create_index(
        "ix_product_categories_category_id", "product_categories", ["category_id"]
    )

    op.create_table(
        "product_images",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "product_id",
            sa.String(),
            sa.ForeignKey(
                "products.id", ondelete="CASCADE", name="fk_product_images_product"
            ),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("alt_text", sa.String(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            # The key shape MediaUploadService builds: stores/{store_id}/{id}.{ext}.
            "storage_key ~ '^stores/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+[.](jpg|png|webp)$'"
            " AND char_length(storage_key) <= 255",
            name="ck_product_images_storage_key",
        ),
        sa.CheckConstraint(
            "alt_text IS NULL OR char_length(alt_text) <= 500",
            name="ck_product_images_alt_text",
        ),
        sa.CheckConstraint("position >= 0", name="ck_product_images_position"),
        sa.UniqueConstraint("storage_key", name="uq_product_images_storage_key"),
        sa.UniqueConstraint(
            "product_id",
            "position",
            name="uq_product_images_product_position",
            deferrable=True,
            initially="DEFERRED",
        ),
    )


def downgrade() -> None:
    op.drop_table("product_images")
    op.drop_table("product_categories")
    op.drop_table("categories")
