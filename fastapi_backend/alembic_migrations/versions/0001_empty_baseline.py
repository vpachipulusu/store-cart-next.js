"""Empty baseline

The template's user and item tables were removed in KAN-30. This revision is a
deliberate no-op root so that `alembic heads` has a single clean base and later
stories add their revisions on top of it (`alembic revision --autogenerate`).
It is never applied by a build: migrations run only from the deploy workflow
that ADR-011 and ADR-005 describe.

Revision ID: 0001
Revises:
Create Date: 2026-10-13
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
