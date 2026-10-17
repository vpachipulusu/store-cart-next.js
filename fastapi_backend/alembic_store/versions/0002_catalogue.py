"""Catalogue: products, variants, options and option values (KAN-70)

Store-database tables only (the platform tree is untouched). Expand-only: new tables.

* Money is integer minor units (``*_minor``, bigint); the currency is a store setting, not
  a column here. Weight is whole grams.
* ``products.slug`` is unique per store (one database per store) and stored lower-case in
  hyphenated form; ``status`` is ``draft`` (default) or ``active``.
* ``variants.sku`` is unique per store, compared case-insensitively.
* A variant picks exactly one value per option: ``variant_option_values`` is keyed by
  (variant, option). Composite foreign keys, all through ``product_id``, force the variant,
  the option and the chosen value to belong to the same product, and the value to belong to
  that option. That a variant covers every option of its product is a service rule.
* ``updated_at`` has only a server default; the writing service sets it on update.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
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
        "products",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), server_default="draft", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            r"title ~ '\S' AND char_length(title) <= 255", name="ck_products_title"
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) <= 200",
            name="ck_products_slug_format",
        ),
        sa.CheckConstraint("status IN ('draft', 'active')", name="ck_products_status"),
        sa.UniqueConstraint("slug", name="uq_products_slug"),
    )

    op.create_table(
        "product_options",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "product_id",
            sa.String(),
            sa.ForeignKey(
                "products.id", ondelete="CASCADE", name="fk_product_options_product"
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            r"name ~ '\S' AND char_length(name) <= 100", name="ck_product_options_name"
        ),
        sa.CheckConstraint("position >= 0", name="ck_product_options_position"),
        # Target of the composite foreign key in variant_option_values.
        sa.UniqueConstraint("id", "product_id", name="uq_product_options_id_product"),
    )
    op.create_index(
        "uq_product_options_product_name",
        "product_options",
        ["product_id", sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "product_option_values",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "option_id",
            sa.String(),
            sa.ForeignKey(
                "product_options.id",
                ondelete="CASCADE",
                name="fk_product_option_values_option",
            ),
            nullable=False,
        ),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            r"value ~ '\S' AND char_length(value) <= 100",
            name="ck_product_option_values_value",
        ),
        sa.CheckConstraint("position >= 0", name="ck_product_option_values_position"),
        # Target of the composite foreign key in variant_option_values.
        sa.UniqueConstraint(
            "id", "option_id", name="uq_product_option_values_id_option"
        ),
    )
    op.create_index(
        "uq_product_option_values_option_value",
        "product_option_values",
        ["option_id", sa.text("lower(value)")],
        unique=True,
    )

    op.create_table(
        "variants",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "product_id",
            sa.String(),
            sa.ForeignKey(
                "products.id", ondelete="CASCADE", name="fk_variants_product"
            ),
            nullable=False,
        ),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=False),
        sa.Column("compare_at_price_minor", sa.BigInteger(), nullable=True),
        sa.Column("weight_grams", sa.Integer(), nullable=True),
        sa.Column("stock", sa.Integer(), server_default="0", nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            # No control characters (newline, tab, ...) and no leading/trailing space.
            r"sku ~ '^[^[:cntrl:][:space:]]([^[:cntrl:]]*[^[:cntrl:][:space:]])?$'"
            " AND char_length(sku) <= 100",
            name="ck_variants_sku_format",
        ),
        sa.CheckConstraint("price_minor >= 0", name="ck_variants_price_minor"),
        sa.CheckConstraint(
            "compare_at_price_minor IS NULL OR compare_at_price_minor > price_minor",
            name="ck_variants_compare_at_above_price",
        ),
        sa.CheckConstraint(
            "weight_grams IS NULL OR weight_grams >= 0", name="ck_variants_weight_grams"
        ),
        sa.CheckConstraint("stock >= 0", name="ck_variants_stock"),
        sa.CheckConstraint("position >= 0", name="ck_variants_position"),
        # Target of the composite foreign key in variant_option_values.
        sa.UniqueConstraint("id", "product_id", name="uq_variants_id_product"),
    )
    op.create_index("ix_variants_product_id", "variants", ["product_id"])
    op.create_index(
        "uq_variants_sku_lower", "variants", [sa.text("lower(sku)")], unique=True
    )

    op.create_table(
        "variant_option_values",
        sa.Column("variant_id", sa.String(), nullable=False),
        sa.Column("option_id", sa.String(), nullable=False),
        sa.Column("option_value_id", sa.String(), nullable=False),
        sa.Column("product_id", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("variant_id", "option_id"),
        sa.ForeignKeyConstraint(
            ["variant_id", "product_id"],
            ["variants.id", "variants.product_id"],
            name="fk_variant_option_values_variant_product",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["option_id", "product_id"],
            ["product_options.id", "product_options.product_id"],
            name="fk_variant_option_values_option_product",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["option_value_id", "option_id"],
            ["product_option_values.id", "product_option_values.option_id"],
            name="fk_variant_option_values_value_option",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    # Deleting an option or a value that a variant still uses is rejected instead of
    # silently stripping the option from the variant. The check is deferred to commit:
    # when a product is deleted, Postgres checks the options before the cascade through
    # variants has removed the links, so even an end-of-statement NO ACTION check would
    # reject the whole-product delete. At commit the links are gone and it passes.
    # Index the referencing columns of the parent-side foreign keys.
    op.create_index(
        "ix_variant_option_values_option_value_id",
        "variant_option_values",
        ["option_value_id"],
    )
    op.create_index(
        "ix_variant_option_values_option_product",
        "variant_option_values",
        ["option_id", "product_id"],
    )


def downgrade() -> None:
    op.drop_table("variant_option_values")
    op.drop_table("variants")
    op.drop_table("product_option_values")
    op.drop_table("product_options")
    op.drop_table("products")
