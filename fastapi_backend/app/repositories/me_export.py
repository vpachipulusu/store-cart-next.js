"""Read side of the personal data export (KAN-120): one user's own rows, nothing else.

Deliberately selects named columns instead of whole models, so a column added to
``users`` later (hashes, secrets, tokens) is never exported by accident. Excluded on
purpose: ``firebase_uid``, ``two_factor_secret``, Stripe identifiers, and every row that
belongs to another user.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform.membership import Membership
from app.models.platform.organization import Organization
from app.models.platform.user import LoginHistory, Notification, User, UserSettings

# Hard cap per list so one export stays bounded; the newest rows win.
MAX_EXPORT_ROWS = 1000


@dataclass(frozen=True)
class ExportProfile:
    id: str
    email: str
    email_verified: bool
    two_factor_enabled: bool
    display_name: str | None
    bio: str | None
    avatar_url: str | None
    location: str | None
    website: str | None
    phone_number: str | None
    last_login_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class ExportSettings:
    theme: str
    email_notifications: bool
    language: str
    timezone: str


@dataclass(frozen=True)
class ExportMembership:
    organization_id: str
    organization_name: str
    organization_slug: str
    role: str
    joined_at: datetime
    subscription_tier: str
    subscription_status: str
    subscription_current_period_end: datetime | None
    subscription_cancel_at_period_end: bool


@dataclass(frozen=True)
class ExportLogin:
    id: str
    ip_address: str | None
    user_agent: str | None
    location: str | None
    login_at: datetime
    successful: bool


@dataclass(frozen=True)
class ExportNotification:
    id: str
    type: str
    title: str
    message: str
    read: bool
    link: str | None
    organization_id: str | None
    store_id: str | None
    created_at: datetime


@dataclass(frozen=True)
class AccountExport:
    profile: ExportProfile
    settings: ExportSettings
    memberships: list[ExportMembership]
    login_history: list[ExportLogin]
    notifications: list[ExportNotification]


class MeExportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def user_id_for_uid(self, uid: str) -> str | None:
        return (
            await self.session.execute(select(User.id).where(User.firebase_uid == uid))
        ).scalar_one_or_none()

    async def collect(self, user_id: str) -> AccountExport | None:
        user = (
            await self.session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            return None
        settings = (
            await self.session.execute(
                select(UserSettings).where(UserSettings.user_id == user_id)
            )
        ).scalar_one_or_none()
        memberships = (
            await self.session.execute(
                select(Membership, Organization)
                .join(Organization, Organization.id == Membership.organization_id)
                .where(Membership.user_id == user_id)
                .order_by(Membership.created_at, Membership.id)
                .limit(MAX_EXPORT_ROWS)
            )
        ).all()
        logins = (
            await self.session.execute(
                select(LoginHistory)
                .where(LoginHistory.user_id == user_id)
                .order_by(LoginHistory.login_at.desc(), LoginHistory.id.desc())
                .limit(MAX_EXPORT_ROWS)
            )
        ).scalars()
        notifications = (
            await self.session.execute(
                select(Notification)
                .where(Notification.user_id == user_id)
                .order_by(Notification.created_at.desc(), Notification.id.desc())
                .limit(MAX_EXPORT_ROWS)
            )
        ).scalars()
        return AccountExport(
            profile=ExportProfile(
                user.id,
                user.email,
                user.email_verified,
                user.two_factor_enabled,
                user.display_name,
                user.bio,
                user.avatar_url,
                user.location,
                user.website,
                user.phone_number,
                user.last_login_at,
                user.created_at,
            ),
            settings=ExportSettings(
                settings.theme if settings else "system",
                settings.email_notifications if settings else True,
                settings.language if settings else "en",
                settings.timezone if settings else "UTC",
            ),
            memberships=[
                ExportMembership(
                    org.id,
                    org.name,
                    org.slug,
                    str(member.role),
                    member.created_at,
                    org.subscription_tier,
                    org.subscription_status,
                    org.stripe_current_period_end,
                    org.stripe_cancel_at_period_end,
                )
                for member, org in memberships
            ],
            login_history=[
                ExportLogin(
                    r.id,
                    r.ip_address,
                    r.user_agent,
                    r.location,
                    r.login_at,
                    r.successful,
                )
                for r in logins
            ],
            notifications=[
                ExportNotification(
                    n.id,
                    n.type,
                    n.title,
                    n.message,
                    n.read,
                    n.link,
                    n.organization_id,
                    n.store_id,
                    n.created_at,
                )
                for n in notifications
            ],
        )
