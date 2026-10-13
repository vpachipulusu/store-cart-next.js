"""Platform database models (ADR-005, ADR-010).

Importing this package registers every table on `Base.metadata`, which Alembic
autogenerate and the metadata test rely on.
"""

from app.models.platform.admin_user import AdminUser
from app.models.platform.app_setting import AppSetting
from app.models.platform.audit_log import AuditLog
from app.models.platform.email_template import EmailTemplate
from app.models.platform.feature_flag import FeatureFlag
from app.models.platform.invitation import Invitation, InvitationStatus
from app.models.platform.membership import Membership, MembershipRole
from app.models.platform.organization import Organization
from app.models.platform.seo_meta import SeoMeta
from app.models.platform.store import Store, StoreStatus
from app.models.platform.url_redirect import UrlRedirect
from app.models.platform.user import LoginHistory, Notification, User, UserSettings

__all__ = [
    "AdminUser",
    "AppSetting",
    "AuditLog",
    "EmailTemplate",
    "FeatureFlag",
    "Invitation",
    "InvitationStatus",
    "LoginHistory",
    "Membership",
    "MembershipRole",
    "Notification",
    "Organization",
    "SeoMeta",
    "Store",
    "StoreStatus",
    "UrlRedirect",
    "User",
    "UserSettings",
]
