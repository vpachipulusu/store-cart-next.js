import os

# app.core.config reads these at import time. The values are placeholders:
# the unit tests never open a database connection. A value already set in the
# environment (CI, a local .env export) takes precedence.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault(
    "BACKEND_INTERNAL_KEY", "test-only-internal-service-key-not-for-deployment"
)
os.environ.setdefault("FIREBASE_ADMIN_PROJECT_ID", "test-project")
os.environ.setdefault("FIREBASE_ADMIN_CLIENT_EMAIL", "test@example.invalid")
os.environ.setdefault(
    "FIREBASE_ADMIN_PRIVATE_KEY", "test-only-placeholder-not-a-real-key"
)
os.environ.setdefault(
    "RATE_LIMIT_EMAIL_KEY", "test-only-email-hmac-key-not-for-deployment"
)
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
)


def _isolate_worker_database() -> None:
    """Give each pytest-xdist worker its own database (KAN-207).

    The real-route tests rebuild the schema of ``TEST_DATABASE_URL`` (alembic
    ``downgrade base`` then ``upgrade head``) and truncate tables between tests,
    so two workers must never share one database. A worker ``gw3`` running
    against ``storecart_test`` uses ``storecart_gw3_test`` instead (see
    ``tests/_worker_db.py``), created on first use, migrated to head and rebuilt by
    the tests themselves. Without xdist (or without a test database) this does nothing,
    so a plain ``pytest`` run is unchanged. Any failure stops the run with a
    clear message rather than letting workers share a database.

    It runs at import time because the test modules read ``TEST_DATABASE_URL``
    when they are imported, and conftest files load before the test modules.
    The server is reached with asyncpg from the URL's host, port, user and
    password only; query parameters (ssl, unix sockets) are not supported.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    base_url = os.environ.get("TEST_DATABASE_URL")
    if not worker or not base_url:
        return

    import asyncio

    import asyncpg  # type: ignore[import-untyped]
    import pytest
    from sqlalchemy.engine import make_url

    from tests._worker_db import worker_database_url

    try:
        worker_url = worker_database_url(base_url, worker)
    except ValueError as error:
        pytest.exit(f"Cannot isolate the {worker} test database: {error}", 4)
    target = make_url(base_url)
    worker_database = worker_url.database or ""

    async def create_if_missing() -> None:
        connection = await asyncpg.connect(
            host=target.host,
            port=target.port or 5432,
            user=target.username,
            password=target.password,
            database=target.database,
            timeout=10,
        )
        try:
            exists = await connection.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", worker_database
            )
            if not exists:
                quoted = worker_database.replace('"', '""')
                try:
                    await connection.execute(f'CREATE DATABASE "{quoted}"')
                except asyncpg.DuplicateDatabaseError:
                    pass  # another checkout created it between the check and now
        finally:
            await connection.close()

    try:
        asyncio.run(create_if_missing())
    except (OSError, TimeoutError, asyncpg.PostgresError) as error:
        pytest.exit(
            f"Cannot create the {worker} test database on {target.host}: "
            f"{type(error).__name__}",
            4,
        )
    os.environ["TEST_DATABASE_URL"] = worker_url.render_as_string(hide_password=False)


_isolate_worker_database()
