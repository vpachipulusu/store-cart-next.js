import enum

from sqlalchemy import CheckConstraint, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base
from app.models.platform.enums import enum_check, enum_column
from app.models.platform.mixins import IdMixin, TimestampMixin


class StoreStatus(enum.StrEnum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class Store(IdMixin, TimestampMixin, Base):
    """Registry entry for one store database (ADR-005). Holds no store data."""

    __tablename__ = "stores"
    __table_args__ = (
        enum_check("status", StoreStatus),
        CheckConstraint("slug = lower(slug)", name="slug_lowercase"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str]
    slug: Mapped[str] = mapped_column(unique=True)
    status: Mapped[StoreStatus] = mapped_column(
        enum_column(StoreStatus),
        server_default=StoreStatus.PROVISIONING.value,
    )
    # Number of store migrations applied to this store's database.
    schema_version: Mapped[int] = mapped_column(server_default=text("0"))
    # Where the store database lives (a reference such as a Neon project and
    # database name). NEVER a connection string or credentials.
    database_ref: Mapped[str | None]
    # AES-256-GCM envelope of the store database connection string (KAN-53). Written
    # and read only through app.services.store_secrets; never returned by any API.
    connection_string_encrypted: Mapped[str | None] = mapped_column()
