"""Database error types, importable without building an engine or loading settings."""

import asyncpg
from sqlalchemy.exc import SQLAlchemyError

# Errors that mean "the database cannot be reached or used right now". Connect-time
# failures are not wrapped by SQLAlchemy: a refused or unreachable host raises
# OSError, the connect timeout raises TimeoutError, and a server refusal (starting
# up, too many connections, bad credentials) raises the asyncpg error itself.
# OSError is deliberately broad (it also covers ssl.SSLError); the readiness check
# logs the root cause type so these stay distinguishable.
DATABASE_UNAVAILABLE_ERRORS: tuple[type[BaseException], ...] = (
    SQLAlchemyError,
    OSError,
    TimeoutError,
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
)


def root_cause_name(error: BaseException) -> str:
    """Class name of the innermost cause, e.g. InvalidPasswordError under a DBAPIError.

    Only the type is returned: driver messages can name the host and database user.
    """
    seen: set[int] = set()
    current = error
    while current.__cause__ is not None and id(current) not in seen:
        seen.add(id(current))
        current = current.__cause__
    return type(current).__name__
