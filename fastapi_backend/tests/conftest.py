import os

# app.core.config reads these at import time. The values are placeholders:
# the unit tests never open a database connection. A value already set in the
# environment (CI, a local .env export) takes precedence.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
)
