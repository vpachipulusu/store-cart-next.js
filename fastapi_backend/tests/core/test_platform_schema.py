"""The platform schema check behind /health/ready (KAN-253).

Production ran code from a deploy whose migration (0010) had not been applied, and
every query that loaded an organisation failed. These pin how an applied revision is
compared with the code's own Alembic head.
"""

from app.core.platform_schema import platform_heads, platform_schema_status


def test_the_platform_tree_has_exactly_one_head() -> None:
    assert len(platform_heads()) == 1


def test_database_at_the_code_head_is_not_pending() -> None:
    (head,) = platform_heads()

    status = platform_schema_status(head)

    assert status.pending is False
    assert status.current == head
    assert status.head == head


def test_database_behind_the_code_head_is_pending() -> None:
    # 0009 is the revision production was on when 0010 (KAN-67) was deployed.
    status = platform_schema_status("0009")

    assert status.pending is True
    assert status.current == "0009"
    assert status.head == platform_heads()[0]


def test_database_with_no_recorded_revision_is_pending() -> None:
    assert platform_schema_status(None).pending is True


def test_database_ahead_of_this_code_is_not_pending() -> None:
    # A newer deploy already migrated the database while this build still serves
    # (rolling deploy): that build is the one the revision belongs to.
    assert platform_schema_status("9999_from_a_newer_build").pending is False
