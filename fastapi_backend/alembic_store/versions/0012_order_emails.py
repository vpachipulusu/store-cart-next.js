"""Transactional order emails: the shopper's address, store templates and the outbox (KAN-81)

Store-database tables only (the platform tree is untouched). Expand-only: one nullable column
and two new tables; no data rewrite. Code from before this revision keeps working: it never
reads or writes them.

* ``orders.customer_email`` is the address Stripe collected on the Checkout Session
  (``customer_details.email``), written once when the order moves to ``paid``. Null for
  orders paid before this revision, or when Stripe sent none.
* ``store_email_templates`` holds a store's own subject and plain-text body for one email
  kind. No row means the platform default (in code). The text is a ``string.Template`` with
  a fixed variable list per kind; HTML is always built by code, never stored.
* ``order_emails`` is the outbox: one row per order and kind, written in the transaction that
  changed the order, then handed to QStash by id. ``status`` moves from ``pending`` to
  ``sent``, ``skipped`` (email disabled or no recipient) or ``failed`` exactly once;
  ``sent_at`` is set exactly when it is ``sent``. Deleting an order deletes its rows.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = "('order_confirmation', 'order_shipped', 'new_order_alert')"


def _timestamps() -> list[sa.Column[sa.DateTime]]:
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
    op.add_column("orders", sa.Column("customer_email", sa.String(), nullable=True))
    # NOT VALID, as 0005 does: the column is new, so every existing row is NULL and there is
    # nothing to scan; new and updated rows are still checked. (A VALIDATE would gain nothing:
    # the store tree runs the whole revision in one transaction.)
    op.execute(
        "ALTER TABLE orders ADD CONSTRAINT ck_orders_customer_email CHECK ("
        "customer_email IS NULL OR (char_length(customer_email) BETWEEN 3 AND 254"
        " AND position('@' in customer_email) > 1)) NOT VALID"
    )

    op.create_table(
        "store_email_templates",
        sa.Column("kind", sa.String(), primary_key=True),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(f"kind IN {KINDS}", name="ck_store_email_templates_kind"),
        sa.CheckConstraint(
            "char_length(subject) BETWEEN 1 AND 200"
            " AND position(chr(13) in subject) = 0"
            " AND position(chr(10) in subject) = 0",
            name="ck_store_email_templates_subject",
        ),
        sa.CheckConstraint(
            "char_length(body_text) BETWEEN 1 AND 10000",
            name="ck_store_email_templates_body_text",
        ),
    )

    op.create_table(
        "order_emails",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "order_id",
            sa.String(),
            sa.ForeignKey(
                "orders.id", ondelete="CASCADE", name="fk_order_emails_order"
            ),
            nullable=False,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        # One row per order and kind; also the index of the foreign key.
        sa.UniqueConstraint("order_id", "kind", name="uq_order_emails_order_kind"),
        sa.CheckConstraint(f"kind IN {KINDS}", name="ck_order_emails_kind"),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'skipped', 'failed')",
            name="ck_order_emails_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_order_emails_attempts"),
        sa.CheckConstraint(
            "(status = 'sent') = (sent_at IS NOT NULL)",
            name="ck_order_emails_sent_at",
        ),
    )


def downgrade() -> None:
    """Drops the outbox, the store templates and the collected addresses.

    Which emails were sent, a store's own wording, and the shoppers' addresses are forgotten
    here; orders, payments and stock are untouched.
    """
    op.drop_table("order_emails")
    op.drop_table("store_email_templates")
    op.drop_constraint("ck_orders_customer_email", "orders", type_="check")
    op.drop_column("orders", "customer_email")
