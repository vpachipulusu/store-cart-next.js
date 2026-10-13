import enum
from datetime import datetime

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base
from app.models.platform.enums import enum_check, enum_column
from app.models.platform.membership import MembershipRole
from app.models.platform.mixins import IdMixin, TimestampMixin


class InvitationStatus(enum.StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class Invitation(IdMixin, TimestampMixin, Base):
    __tablename__ = "invitations"
    __table_args__ = (
        Index("ix_invitations_organization_id_email", "organization_id", "email"),
        enum_check("role", MembershipRole),
        enum_check("status", InvitationStatus),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    email: Mapped[str]
    role: Mapped[MembershipRole] = mapped_column(enum_column(MembershipRole))
    # Only a hash of the invitation token is stored, never the token itself.
    token_hash: Mapped[str] = mapped_column(unique=True)
    status: Mapped[InvitationStatus] = mapped_column(
        enum_column(InvitationStatus),
        server_default=InvitationStatus.PENDING.value,
    )
    invited_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime]
    accepted_at: Mapped[datetime | None]
