"""Per-worker test database naming for pytest-xdist runs (KAN-207)."""

from sqlalchemy.engine import URL, make_url

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def worker_database_url(base_url: str, worker: str) -> URL:
    """Return ``base_url`` pointed at the database private to ``worker``.

    ``storecart_test`` and worker ``gw3`` give ``storecart_gw3_test``: the name
    keeps the ``_test`` suffix the tests insist on. Raises ``ValueError`` for a
    URL the tests would refuse anyway (not a local ``*_test`` database), so a
    worker never silently falls back to a shared database.
    """
    target = make_url(base_url)
    database = target.database or ""
    if not database.endswith("_test"):
        raise ValueError("TEST_DATABASE_URL must name a database ending in _test")
    if target.host not in LOCAL_HOSTS:
        raise ValueError("TEST_DATABASE_URL must point at a local host")
    return target.set(database=f"{database.removesuffix('_test')}_{worker}_test")
