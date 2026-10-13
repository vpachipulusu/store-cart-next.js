from typing import Any

from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base
from app.models.platform.mixins import IdMixin, TimestampMixin


class AdminUser(IdMixin, TimestampMixin, Base):
    """Platform operator role ("admin", "super_admin"), separate from memberships."""

    __tablename__ = "admin_users"
    __table_args__ = (Index("ix_admin_users_user_id_role", "user_id", "role"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    role: Mapped[str] = mapped_column(server_default="admin")
    permissions: Mapped[Any] = mapped_column(JSONB)  # array of permission strings
