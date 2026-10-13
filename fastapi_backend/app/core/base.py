from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for models.

    Lives apart from `app.core.database` so Alembic can import the metadata
    without loading application settings.
    """
