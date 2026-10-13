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
