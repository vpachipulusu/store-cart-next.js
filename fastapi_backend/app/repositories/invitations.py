"""Team members and invitations of one organisation (KAN-62).

Only ``token_hash`` is ever stored or read; no method takes or returns a raw token, and
``InvitationRecord`` has no hash field, so a record can be returned to a caller as is.
Emails arrive canonical (``canonical_email`` in the service), the form invitations are
stored in; user emails are lower-cased in the query, since they may not be.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.models.platform.invitation import Invitation, InvitationStatus
from app.models.platform.membership import Membership, MembershipRole
from app.models.platform.user import User
from app.repositories.base import BaseRepository


@dataclass(frozen=True)
class InvitationRecord:
    id: str
    organization_id: str
    email: str
    role: MembershipRole
    status: InvitationStatus
    expires_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class MemberRecord:
    user_id: str
    email: str
    display_name: str | None
    role: MembershipRole
    joined_at: datetime


def _invitation(row: Invitation) -> InvitationRecord:
    return InvitationRecord(
        row.id,
        row.organization_id,
        row.email,
        row.role,
        row.status,
        row.expires_at,
        row.created_at,
    )


def _pending(organization_id: str, now: datetime) -> tuple[ColumnElement[bool], ...]:
    return (
        Invitation.organization_id == organization_id,
        Invitation.status == InvitationStatus.PENDING,
        Invitation.expires_at > now,
    )


class InvitationsRepository(BaseRepository):
    async def list_members(
        self, organization_id: str, limit: int, offset: int
    ) -> tuple[list[MemberRecord], int]:
        total = await self.count_members(organization_id)
        rows = (
            await self._session.execute(
                select(
                    User.id,
                    User.email,
                    User.display_name,
                    Membership.role,
                    Membership.created_at,
                )
                .join(Membership, Membership.user_id == User.id)
                .where(Membership.organization_id == organization_id)
                .order_by(Membership.created_at, Membership.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return [MemberRecord(*row) for row in rows], total

    async def count_members(self, organization_id: str) -> int:
        return (
            await self._session.execute(
                select(func.count())
                .select_from(Membership)
                .where(Membership.organization_id == organization_id)
            )
        ).scalar_one()

    async def is_member_email(self, organization_id: str, email: str) -> bool:
        """``email`` is canonical (lower-case); stored user emails may not be."""
        found = (
            await self._session.execute(
                select(Membership.id)
                .join(User, User.id == Membership.user_id)
                .where(
                    Membership.organization_id == organization_id,
                    func.lower(User.email) == email,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return found is not None

    async def list_pending(
        self, organization_id: str, now: datetime
    ) -> list[InvitationRecord]:
        rows = (
            await self._session.execute(
                select(Invitation)
                .where(*_pending(organization_id, now))
                .order_by(Invitation.created_at, Invitation.id)
            )
        ).scalars()
        return [_invitation(row) for row in rows]

    async def count_pending(self, organization_id: str, now: datetime) -> int:
        return (
            await self._session.execute(
                select(func.count())
                .select_from(Invitation)
                .where(*_pending(organization_id, now))
            )
        ).scalar_one()

    async def revoke_pending_for(self, organization_id: str, email: str) -> int:
        """Revoke the open invitations for ``email`` (canonical); how many there were."""
        result = await self._session.execute(
            update(Invitation)
            .where(
                Invitation.organization_id == organization_id,
                Invitation.status == InvitationStatus.PENDING,
                Invitation.email == email,
            )
            .values(status=InvitationStatus.REVOKED)
            .returning(Invitation.id)
        )
        return len(result.all())

    async def expire_stale(self, organization_id: str, now: datetime) -> None:
        """Mark PENDING invitations whose time has passed as EXPIRED."""
        await self._session.execute(
            update(Invitation)
            .where(
                Invitation.organization_id == organization_id,
                Invitation.status == InvitationStatus.PENDING,
                Invitation.expires_at <= now,
            )
            .values(status=InvitationStatus.EXPIRED)
        )

    async def insert(
        self,
        *,
        organization_id: str,
        email: str,
        role: MembershipRole,
        token_hash: str,
        invited_by_user_id: str,
        expires_at: datetime,
    ) -> InvitationRecord:
        row = (
            await self._session.execute(
                insert(Invitation)
                .values(
                    organization_id=organization_id,
                    email=email,
                    role=role,
                    token_hash=token_hash,
                    status=InvitationStatus.PENDING,
                    invited_by_user_id=invited_by_user_id,
                    expires_at=expires_at,
                )
                .returning(Invitation)
            )
        ).scalar_one()
        return _invitation(row)

    async def find_by_token_hash(self, token_hash: str) -> InvitationRecord | None:
        row = (
            await self._session.execute(
                select(Invitation).where(Invitation.token_hash == token_hash)
            )
        ).scalar_one_or_none()
        return _invitation(row) if row else None

    async def claim(
        self, token_hash: str, email: str, now: datetime
    ) -> InvitationRecord | None:
        """Spend a PENDING, unexpired invitation for ``email`` (canonical); else None.

        One conditional UPDATE: of two concurrent claims only one sees PENDING.
        """
        row = (
            await self._session.execute(
                update(Invitation)
                .where(
                    Invitation.token_hash == token_hash,
                    Invitation.status == InvitationStatus.PENDING,
                    Invitation.expires_at > now,
                    Invitation.email == email,
                )
                .values(status=InvitationStatus.ACCEPTED, accepted_at=now)
                .returning(Invitation)
            )
        ).scalar_one_or_none()
        return _invitation(row) if row else None
