"""Admin audit trail (KAN-46): build one append-only entry per admin change.

Entries are staged in the caller's transaction, so the change and its audit row
commit or roll back together: if the audit write fails, the change does not stick.
Denied requests write no row (they are logged, without payload, by ``require_admin``).
"""

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Protocol

from app.core.permissions import AdminContext

REDACTED = "[REDACTED]"
MAX_DEPTH = 6
MAX_ITEMS = 50
MAX_STRING = 500

# Matched against the lower-cased key with non-alphanumerics removed. Covers
# secrets, credentials, TOTP/2FA material and the raw PII the ticket excludes
# (email, phone, address); log ids and changed field names instead of values.
_SENSITIVE_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "apikey",
    "privatekey",
    "secretkey",
    "signingkey",
    "internalkey",
    "accesskey",
    "authorization",
    "cookie",
    "session",
    "credential",
    "totp",
    "twofactor",
    "mfa",
    "backupcode",
    "recoverycode",
    "salt",
    "email",
    "phone",
    "address",
)
_SENSITIVE_EXACT = frozenset({"key", "otp", "pin", "code", "hash"})
_ACTION_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_RESOURCE_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def _is_sensitive(key: object) -> bool:
    normalised = re.sub(r"[^a-z0-9]", "", str(key).lower())
    return normalised in _SENSITIVE_EXACT or any(
        part in normalised for part in _SENSITIVE_PARTS
    )


def sanitize(value: Any, depth: int = 0) -> Any:
    """JSON-safe copy of ``value`` with secret-looking keys redacted and size bounded."""
    if depth > MAX_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _is_sensitive(key) else sanitize(item, depth + 1)
            for key, item in list(value.items())[:MAX_ITEMS]
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [sanitize(item, depth + 1) for item in list(value)[:MAX_ITEMS]]
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:MAX_STRING]
    if isinstance(value, datetime | date):
        return value.isoformat()
    # Unknown objects (SecretStr, models, ...): record the type, never the value.
    return f"<{type(value).__name__}>"


class AuditWriter(Protocol):
    async def add(
        self,
        *,
        user_id: str,
        organization_id: str | None,
        action: str,
        resource: str,
        resource_id: str | None,
        metadata: dict[str, Any],
        ip_address: str | None,
        user_agent: str | None,
    ) -> None: ...


class AuditService:
    def __init__(self, repository: AuditWriter) -> None:
        self.repository = repository

    async def record_admin_action(
        self,
        admin: AdminContext,
        *,
        action: str,
        resource: str,
        resource_id: str | None = None,
        organization_id: str | None = None,
        before: Any = None,
        after: Any = None,
        details: Any = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Stage one audit row.

        ``action`` is ``<area>.<verb>`` (for example ``admin.users.update``),
        ``resource`` the table-like target name, ``resource_id`` the target id.
        A malformed action or resource is a programming error and raises.
        """
        if not _ACTION_RE.match(action):
            raise ValueError("Invalid audit action")
        if not _RESOURCE_RE.match(resource):
            raise ValueError("Invalid audit resource")
        metadata: dict[str, Any] = {"actor_role": admin.role}
        for key, value in (
            ("request_id", request_id),
            ("before", before),
            ("after", after),
            ("details", details),
        ):
            if value is not None:
                metadata[key] = sanitize(value)
        await self.repository.add(
            user_id=admin.user_id,
            organization_id=organization_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            metadata=metadata,
            ip_address=ip_address,
            user_agent=user_agent[:512] if user_agent else None,
        )
