"""Is the platform database at the Alembic head this build was written for? (KAN-253)

No deploy runs ``alembic upgrade head`` (ADR-011). When a backend PR with a platform
migration is deployed before the migration is applied, every query on the changed
tables fails. ``/health/ready`` uses this to answer 503 with the applied and expected
revisions instead of the service failing request by request.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError

PLATFORM_SCRIPT_LOCATION = Path(__file__).resolve().parents[2] / "alembic_migrations"


@dataclass(frozen=True)
class PlatformSchemaStatus:
    pending: bool
    current: str | None
    head: str


@lru_cache(maxsize=1)
def _scripts() -> ScriptDirectory:
    return ScriptDirectory(str(PLATFORM_SCRIPT_LOCATION))


def platform_heads() -> tuple[str, ...]:
    """The head revision(s) of this build's platform migration tree."""
    return tuple(_scripts().get_heads())


def _known(revision: str) -> bool:
    try:
        return _scripts().get_revision(revision) is not None
    except CommandError:
        return False


def platform_schema_status(current: str | None) -> PlatformSchemaStatus:
    """Compare the applied revision with this build's head.

    Pending when nothing is recorded, or when the applied revision is an older one
    of this tree. A revision this build does not know belongs to a newer build that
    already migrated (rolling deploy), so it is not pending here.
    """
    heads = platform_heads()
    pending = current is None or (current not in heads and _known(current))
    return PlatformSchemaStatus(pending=pending, current=current, head=heads[0])
