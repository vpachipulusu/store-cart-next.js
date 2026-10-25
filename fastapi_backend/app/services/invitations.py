"""Team members and invitations (KAN-62).

Rules:

* only an OWNER or ADMIN of the organisation lists the team and invites (STAFF gets
  ``OrgForbidden``, a non-member ``OrganizationNotFound``); nobody is invited as OWNER;
* an invitation is a ``secrets.token_urlsafe(32)`` token of which only the sha256 is
  stored. The accept link is returned once, by ``create_invitation``, and emailed; it is
  never listed, logged or audited;
* it expires ``INVITATION_TTL`` after creation and is spent by the first accept;
* accepting is bound to the signed-in user's verified email (case-insensitive) and runs in
  one transaction under the organisation row lock: a conditional UPDATE spends the
  invitation, then the staff limit is checked, then the membership is inserted. Any
  failure rolls the whole transaction back, so a refused accept leaves it PENDING.
"""

import hashlib
import html
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform.invitation import InvitationStatus
from app.models.platform.membership import MembershipRole
from app.repositories.audit import AuditRepository
from app.repositories.invitations import (
    InvitationRecord,
    InvitationsRepository,
    MemberRecord,
)
from app.repositories.organizations import OrganizationRecord, OrganizationsRepository
from app.services.audit import sanitize
from app.services.email import EmailDeliveryFailed, EmailMessage, EmailSender
from app.services.organizations import (
    MANAGE_ROLES,
    OrganizationNotFound,
    OrgForbidden,
)
from app.services.plan_limits import require_staff_capacity

logger = logging.getLogger("storecart.invitations")

INVITATION_TTL = timedelta(days=7)
INVITABLE_ROLES = frozenset({MembershipRole.ADMIN, MembershipRole.STAFF})
# Abuse guard: open invitations one organisation may have at a time.
MAX_PENDING_INVITATIONS = 50
MAX_EMAIL_LENGTH = 254
TOKEN_BYTES = 32


class InvalidInvitationRole(ValueError):
    """The role cannot be invited (OWNER) (422)."""


class InvalidEmail(ValueError):
    """The email address is not usable (422)."""


class AlreadyMember(Exception):
    """The invited (or accepting) person is already a member (409)."""


class InvitationAlreadyPending(Exception):
    """An open invitation for this email already exists (409)."""


class TooManyPendingInvitations(Exception):
    """The organisation has too many open invitations (409)."""


class InvitationInvalid(Exception):
    """No such invitation, or it was already used, revoked or has expired (410)."""


class InvitationEmailMismatch(Exception):
    """The invitation was sent to a different email address (403)."""


class InvitationsUnavailable(Exception):
    """The app URL for accept links is not configured (503)."""


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(raw: str) -> str:
    email = raw.strip().lower()
    local, _, domain = email.partition("@")
    if (
        not local
        or not domain
        or len(email) > MAX_EMAIL_LENGTH
        or any(char.isspace() or not char.isprintable() for char in email)
    ):
        raise InvalidEmail
    return email


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class TeamView:
    members: list[MemberRecord]
    invitations: list[InvitationRecord]


@dataclass(frozen=True)
class CreatedInvitation:
    invitation: InvitationRecord
    # Shown to the inviter once; never stored, listed or logged.
    accept_url: str
    email_sent: bool


@dataclass(frozen=True)
class AcceptedInvitation:
    organization_id: str
    role: MembershipRole


class InvitationsService:
    def __init__(
        self,
        invitations: InvitationsRepository,
        organizations: OrganizationsRepository,
        session: AsyncSession,
        sender: EmailSender,
        app_url: str | None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._invitations = invitations
        self._organizations = organizations
        self._session = session
        self._sender = sender
        self._app_url = app_url
        self._clock = clock
        self._audit = AuditRepository(session)

    # Reads -----------------------------------------------------------------

    async def list_members(
        self, organization_id: str, user_id: str
    ) -> list[MemberRecord]:
        await self._require_manager(organization_id, user_id)
        members = await self._invitations.list_members(organization_id)
        await self._session.rollback()
        return members

    async def list_invitations(
        self, organization_id: str, user_id: str
    ) -> list[InvitationRecord]:
        await self._require_manager(organization_id, user_id)
        pending = await self._invitations.list_pending(organization_id, self._clock())
        await self._session.rollback()
        return pending

    # Create ----------------------------------------------------------------

    async def create_invitation(
        self,
        organization_id: str,
        user_id: str,
        *,
        email: str,
        role: MembershipRole,
        request_id: str | None,
    ) -> CreatedInvitation:
        if role not in INVITABLE_ROLES:
            raise InvalidInvitationRole
        clean_email = normalize_email(email)
        if self._app_url is None:
            raise InvitationsUnavailable
        # Unlocked check first, so a non-member can neither learn the organisation
        # exists nor hold its lock; then lock and re-read the role.
        await self._require_manager(organization_id, user_id)
        organization = await self._lock_managed(organization_id, user_id)
        try:
            invitation, token = await self._insert(
                organization, user_id, clean_email, role, request_id
            )
        except Exception:
            await self._session.rollback()
            raise
        await self._session.commit()
        accept_url = f"{self._app_url}/invite/{token}"
        sent = await self._send(organization, invitation, accept_url)
        return CreatedInvitation(invitation, accept_url, sent)

    async def _insert(
        self,
        organization: OrganizationRecord,
        user_id: str,
        email: str,
        role: MembershipRole,
        request_id: str | None,
    ) -> tuple[InvitationRecord, str]:
        now = self._clock()
        if await self._invitations.is_member_email(organization.id, email):
            raise AlreadyMember
        await self._invitations.expire_stale(organization.id, now)
        if await self._invitations.has_pending_for(organization.id, email, now):
            raise InvitationAlreadyPending
        pending = await self._invitations.count_pending(organization.id, now)
        if pending >= MAX_PENDING_INVITATIONS:
            raise TooManyPendingInvitations
        # Open invitations hold a seat, so the plan cannot be oversold by invitations
        # that would all fail on accept. Accept checks members alone again.
        members = await self._invitations.count_members(organization.id)
        require_staff_capacity(members + pending, organization.effective_plan)
        token = secrets.token_urlsafe(TOKEN_BYTES)
        invitation = await self._invitations.insert(
            organization_id=organization.id,
            email=email,
            role=role,
            token_hash=hash_token(token),
            invited_by_user_id=user_id,
            expires_at=now + INVITATION_TTL,
        )
        await self._record(
            user_id,
            "invitation.create",
            invitation.id,
            organization.id,
            {"role": role, "expires_at": invitation.expires_at},
            request_id,
        )
        return invitation, token

    async def _send(
        self,
        organization: OrganizationRecord,
        invitation: InvitationRecord,
        accept_url: str,
    ) -> bool:
        """Email the link; False (never an error) when it cannot be delivered."""
        name = organization.name
        role = invitation.role.value.lower()
        message = EmailMessage(
            to=invitation.email,
            subject=f"You're invited to join {name} on StoreCart",
            text=(
                f"You have been invited to join {name} on StoreCart as {role}.\n\n"
                f"Accept the invitation: {accept_url}\n\n"
                "The link works once and expires in 7 days. Sign in with this email "
                "address to accept it. If you did not expect this, ignore this email."
            ),
            html=(
                f"<p>You have been invited to join <strong>{html.escape(name)}"
                f"</strong> on StoreCart as {role}.</p>"
                f'<p><a href="{html.escape(accept_url, quote=True)}">'
                "Accept the invitation</a></p>"
                "<p>The link works once and expires in 7 days. Sign in with this email "
                "address to accept it. If you did not expect this, ignore this email."
                "</p>"
            ),
            kind="invitation",
        )
        try:
            await self._sender.send(message)
        except EmailDeliveryFailed:
            return False
        except Exception as exc:  # noqa: BLE001 - the invitation is committed already
            logger.error("invitation email crashed: %s", type(exc).__name__)
            return False
        return True

    # Accept ----------------------------------------------------------------

    async def accept(
        self,
        token: str,
        user_id: str,
        email: str,
        *,
        request_id: str | None,
    ) -> AcceptedInvitation:
        token_hash = hash_token(token)
        found = await self._invitations.find_by_token_hash(token_hash)
        if found is None:
            await self._session.rollback()
            raise InvitationInvalid
        try:
            accepted = await self._accept_locked(
                found, token_hash, user_id, email, request_id
            )
        except Exception:
            await self._session.rollback()
            raise
        await self._session.commit()
        return accepted

    async def _accept_locked(
        self,
        found: InvitationRecord,
        token_hash: str,
        user_id: str,
        email: str,
        request_id: str | None,
    ) -> AcceptedInvitation:
        organization = await self._organizations.get_organization(
            found.organization_id, lock=True
        )
        if organization is None:
            raise InvitationInvalid
        now = self._clock()
        claimed = await self._invitations.claim(token_hash, email, now)
        if claimed is None:
            if (
                found.status is InvitationStatus.PENDING
                and found.expires_at > now
                and found.email.lower() != email.strip().lower()
            ):
                raise InvitationEmailMismatch
            raise InvitationInvalid
        if await self._organizations.get_role(organization.id, user_id) is not None:
            raise AlreadyMember
        members = await self._invitations.count_members(organization.id)
        require_staff_capacity(members, organization.effective_plan)
        await self._organizations.add_membership(organization.id, user_id, claimed.role)
        await self._record(
            user_id,
            "invitation.accept",
            claimed.id,
            organization.id,
            {"role": claimed.role},
            request_id,
        )
        return AcceptedInvitation(organization.id, claimed.role)

    # Helpers ---------------------------------------------------------------

    async def _require_manager(self, organization_id: str, user_id: str) -> None:
        role = await self._organizations.get_role(organization_id, user_id)
        if role is None:
            raise OrganizationNotFound
        if role not in MANAGE_ROLES:
            raise OrgForbidden

    async def _lock_managed(
        self, organization_id: str, user_id: str
    ) -> OrganizationRecord:
        organization = await self._organizations.get_organization(
            organization_id, lock=True
        )
        role = await self._organizations.get_role(organization_id, user_id)
        if organization is None or role is None:
            await self._session.rollback()
            raise OrganizationNotFound
        if role not in MANAGE_ROLES:
            await self._session.rollback()
            raise OrgForbidden
        return organization

    async def _record(
        self,
        user_id: str,
        action: str,
        invitation_id: str,
        organization_id: str,
        after: dict[str, Any],
        request_id: str | None,
    ) -> None:
        metadata: dict[str, Any] = {"after": sanitize(after)}
        if request_id is not None:
            metadata["request_id"] = sanitize(request_id)
        await self._audit.add(
            user_id=user_id,
            organization_id=organization_id,
            action=action,
            resource="invitation",
            resource_id=invitation_id,
            metadata=metadata,
            ip_address=None,
            user_agent=None,
        )
