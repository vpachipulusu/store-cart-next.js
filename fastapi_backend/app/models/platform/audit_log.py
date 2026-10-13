from typing import Any

from sqlalchemy import Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base
from app.models.platform.mixins import CreatedAtMixin, IdMixin


class AuditLog(IdMixin, CreatedAtMixin, Base):
    """Append-only trail. No foreign keys, so rows outlive users and organisations."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_id_created_at", "user_id", "created_at"),
        Index("ix_audit_logs_action_created_at", "action", "created_at"),
        Index("ix_audit_logs_resource_resource_id", "resource", "resource_id"),
        Index(
            "ix_audit_logs_organization_id_created_at", "organization_id", "created_at"
        ),
    )

    user_id: Mapped[str | None]
    organization_id: Mapped[str | None]
    action: Mapped[str]
    resource: Mapped[str]
    resource_id: Mapped[str | None]
    metadata_: Mapped[Any | None] = mapped_column("metadata", JSONB)
    ip_address: Mapped[str | None]
    user_agent: Mapped[str | None]
