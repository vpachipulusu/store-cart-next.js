"""Pure parts of the store role backfill (KAN-238); the database path is in
test_store_roles_e2e.py."""

import pytest
from sqlalchemy.engine import make_url

from app.services.store_role_backfill import (
    BackfillFailure,
    BackfillReport,
    direct_endpoint,
)


@pytest.mark.parametrize(
    ("pooled", "host"),
    [
        (
            "postgresql://o:p@ep-cool-1-pooler.eu-west-2.aws.neon.tech/store_a?sslmode=require",
            "ep-cool-1.eu-west-2.aws.neon.tech",
        ),
        ("postgresql://o:p@localhost:5432/store_a", "localhost"),
        ("postgresql://o:p@db.local/store_a", "db.local"),
    ],
)
def test_direct_endpoint_drops_only_the_neon_pooler_suffix(pooled: str, host: str):
    direct = make_url(direct_endpoint(pooled))
    source = make_url(pooled)

    assert direct.host == host
    assert (direct.username, direct.password, direct.database, direct.query) == (
        source.username,
        source.password,
        source.database,
        source.query,
    )


def test_report_succeeds_only_without_a_failed_store():
    assert BackfillReport(moved=("a",)).succeeded
    assert not BackfillReport(failures=(BackfillFailure("b", "Boom"),)).succeeded
