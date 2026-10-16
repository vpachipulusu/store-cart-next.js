from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base
from app.models.platform.mixins import CreatedAtMixin, IdMixin, TimestampMixin


class User(IdMixin, TimestampMixin, Base):
    """A person. Billing lives on Organization (ADR-010), not here."""

    __tablename__ = "users"

    firebase_uid: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str] = mapped_column(unique=True)
    email_verified: Mapped[bool] = mapped_column(server_default=text("false"))
    last_login_at: Mapped[datetime | None]

    display_name: Mapped[str | None]
    bio: Mapped[str | None]
    avatar_url: Mapped[str | None]
    location: Mapped[str | None]
    website: Mapped[str | None]
    phone_number: Mapped[str | None]

    two_factor_enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    two_factor_secret: Mapped[str | None]


class UserSettings(IdMixin, TimestampMixin, Base):
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    theme: Mapped[str] = mapped_column(server_default="system")
    email_notifications: Mapped[bool] = mapped_column(server_default=text("true"))
    language: Mapped[str] = mapped_column(server_default="en")
    timezone: Mapped[str] = mapped_column(server_default="UTC")


class LoginHistory(IdMixin, Base):
    __tablename__ = "login_history"
    __table_args__ = (
        Index("ix_login_history_user_id_login_at", "user_id", "login_at"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    ip_address: Mapped[str | None]
    user_agent: Mapped[str | None]
    location: Mapped[str | None]
    login_at: Mapped[datetime] = mapped_column(server_default=func.now())
    successful: Mapped[bool] = mapped_column(server_default=text("true"))


class Notification(IdMixin, CreatedAtMixin, Base):
    """An in-app notification for one user, optionally scoped to an organisation or store."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_id_read", "user_id", "read"),
        Index("ix_notifications_user_id_created_at", "user_id", "created_at"),
        Index("ix_notifications_user_id_organization_id", "user_id", "organization_id"),
        Index("ix_notifications_user_id_store_id", "user_id", "store_id"),
        CheckConstraint(
            "store_id IS NULL OR organization_id IS NOT NULL",
            name="store_requires_organization",
        ),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Scope (KAN-40): both null is a personal notification. A store scope also carries
    # the store's organisation so an organisation filter finds its stores' notifications.
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    store_id: Mapped[str | None] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE")
    )
    type: Mapped[str]
    title: Mapped[str]
    message: Mapped[str]
    read: Mapped[bool] = mapped_column(server_default=text("false"))
    link: Mapped[str | None]
