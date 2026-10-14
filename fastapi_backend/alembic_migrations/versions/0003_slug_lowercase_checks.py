"""Lower-case slug checks (KAN-59)

Slugs are compared case-insensitively by storing them lower-case: the existing unique
constraints on `organizations.slug` and `stores.slug` then give case-insensitive
uniqueness, and these CHECKs stop any writer from storing a mixed-case slug.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    for table in ("organizations", "stores"):
        bad = connection.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE slug <> lower(slug)")
        ).scalar_one()
        if bad:
            raise RuntimeError(
                f"{bad} {table} row(s) have a mixed-case slug; lower-case them "
                "(resolving any collisions) before running this migration"
            )
    for table in ("organizations", "stores"):
        op.create_check_constraint(
            op.f(f"ck_{table}_slug_lowercase"), table, "slug = lower(slug)"
        )


def downgrade() -> None:
    for table in ("stores", "organizations"):
        op.drop_constraint(op.f(f"ck_{table}_slug_lowercase"), table, type_="check")
