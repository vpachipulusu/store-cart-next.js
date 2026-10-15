"""Alembic environment for store databases (KAN-57).

Unlike the platform tree this environment never builds an engine: the caller
(``app.services.store_migrations``) opens the store connection through the store session
machinery and passes it in ``config.attributes["connection"]``. That keeps every store
engine behind ``app/services/store_sessions.py`` (ruff TID251) and keeps connection
strings out of Alembic configuration.
"""

from alembic import context

config = context.config


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is None:
        raise RuntimeError(
            "store migrations run only through app.services.store_migrations"
        )
    context.configure(
        connection=connection,
        target_metadata=None,
        # Kept apart from the platform ``alembic_version`` table; set by the caller.
        version_table=config.attributes["version_table"],
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("store migrations do not support offline mode")
run_migrations_online()
