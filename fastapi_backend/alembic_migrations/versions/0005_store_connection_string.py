"""Encrypted store connection string (KAN-53)

Adds `stores.connection_string_encrypted`, an AES-256-GCM envelope written only by
app.services.store_secrets. Existing rows start NULL (no connection string yet).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-15
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
    op.add_column(
        "stores", sa.Column("connection_string_encrypted", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("stores", "connection_string_encrypted")
