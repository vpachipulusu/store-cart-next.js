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
    against ``storecart_test`` uses ``storecart_gw3_test`` instead, created on
    first use and rebuilt by the tests themselves. The name keeps the ``_test``
    suffix the tests insist on. Without xdist (or without a test database) this
    does nothing, so a plain ``pytest`` run is unchanged.

    It runs at import time because the test modules read ``TEST_DATABASE_URL``
    when they are imported, and conftest files load before the test modules.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    base_url = os.environ.get("TEST_DATABASE_URL")
    if not worker or not base_url:
        return

    import asyncio

    import asyncpg  # type: ignore[import-untyped]
    from sqlalchemy.engine import make_url

    target = make_url(base_url)
    database = target.database or ""
    # The tests refuse a non-local or non-*_test database; do not create one either.
    if not database.endswith("_test") or target.host not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        return
    worker_database = f"{database.removesuffix('_test')}_{worker}_test"

    async def create_if_missing() -> None:
        connection = await asyncpg.connect(
            host=target.host,
            port=target.port or 5432,
            user=target.username,
            password=target.password,
            database=database,
        )
        try:
            exists = await connection.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", worker_database
            )
            if not exists:
                quoted = worker_database.replace('"', '""')
                await connection.execute(f'CREATE DATABASE "{quoted}"')
        finally:
            await connection.close()

    asyncio.run(create_if_missing())
    os.environ["TEST_DATABASE_URL"] = target.set(
        database=worker_database
    ).render_as_string(hide_password=False)


_isolate_worker_database()
