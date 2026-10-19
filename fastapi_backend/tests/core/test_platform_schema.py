"""The platform schema check behind /health/ready (KAN-253).

Production ran code from a deploy whose migration (0010) had not been applied, and
every query that loaded an organisation failed. These pin how an applied revision is
compared with the code's own Alembic head.
"""

from pathlib import Path

from alembic.script import ScriptDirectory

from app.core.platform_schema import (
    PLATFORM_HEAD,
    PLATFORM_REVISIONS,
    platform_schema_status,
)

SCRIPT_LOCATION = Path(__file__).resolve().parents[2] / "alembic_migrations"


def test_revision_constants_match_the_migration_tree() -> None:
    # Adding a platform migration without appending it to PLATFORM_REVISIONS fails here.
    scripts = ScriptDirectory(str(SCRIPT_LOCATION))
    heads = scripts.get_heads()
    oldest_first = [script.revision for script in scripts.walk_revisions()][::-1]

    assert len(heads) == 1
    assert heads[0] == PLATFORM_HEAD
    assert tuple(oldest_first) == PLATFORM_REVISIONS


def test_database_at_the_code_head_is_not_pending() -> None:
    status = platform_schema_status(PLATFORM_HEAD)

    assert status.pending is False
    assert status.current == PLATFORM_HEAD
    assert status.head == PLATFORM_HEAD


def test_database_behind_the_code_head_is_pending() -> None:
    # The revision production was on when the head's migration was deployed.
    previous = PLATFORM_REVISIONS[-2]

    status = platform_schema_status(previous)

    assert status.pending is True
    assert status.current == previous
    assert status.head == PLATFORM_HEAD


def test_database_with_no_recorded_revision_is_pending() -> None:
    assert platform_schema_status(None).pending is True


def test_database_ahead_of_this_code_is_not_pending() -> None:
    # A newer deploy already migrated the database while this build still serves
    # (rolling deploy): that build is the one the revision belongs to.
    assert platform_schema_status("9999_from_a_newer_build").pending is False
