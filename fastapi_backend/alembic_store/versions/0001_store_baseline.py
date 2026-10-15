"""Store baseline (KAN-57)

Marks a freshly provisioned store database as version 1. It creates no tables: the first
store tables arrive with the catalogue stories, each as its own revision here.

Revision ID: 0001
Revises:
Create Date: 2026-10-15
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Intentionally empty."""


def downgrade() -> None:
    """Intentionally empty."""
