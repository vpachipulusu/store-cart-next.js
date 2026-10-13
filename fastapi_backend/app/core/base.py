from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, MetaData, Text
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint and index names keep migrations stable and let
# `alembic check` compare names, not only shapes.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for platform models (ADR-005: the `platform` metadata).

    Lives apart from `app.core.database` so Alembic can import the metadata
    without loading application settings. Store databases get their own base and
    Alembic tree later (E7); do not add store data here.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map: ClassVar[dict[Any, Any]] = {
        str: Text,
        datetime: DateTime(timezone=True),
    }
