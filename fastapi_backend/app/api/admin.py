"""Platform-admin authorisation and audit dependencies (KAN-46).

Usage in an admin route (KAN-47/48/49)::

    admin: Annotated[AdminContext, Depends(require_admin("users.update"))]
    auditor: AuditorDep
    ...
    await auditor.record(admin, action="admin.users.update", resource="users", ...)
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Request

from app.api.auth import get_current_identity
from app.api.deps import SessionDep
from app.api.rate_limit import client_ip
from app.core.firebase import VerifiedIdentity
from app.core.permissions import (
    AdminContext,
    effective_permissions,
    validate_required,
)
from app.repositories.admin import AdminGrant, AdminRepository
from app.repositories.audit import AuditRepository
from app.services.audit import AuditService

logger = logging.getLogger(__name__)

FORBIDDEN = "Forbidden"


class AdminLookup(Protocol):
    async def get_grant(self, uid: str) -> AdminGrant | None: ...


def get_admin_repository(session: SessionDep) -> AdminLookup:
    return AdminRepository(session)


AdminRepositoryDep = Annotated[AdminLookup, Depends(get_admin_repository)]


def require_admin(*permissions: str) -> Callable[..., Awaitable[AdminContext]]:
    """Dependency factory: the caller must be a platform admin holding every permission.

    Authentication is the existing session dependency (401 without a valid session,
    403 for an unverified email). Authorisation reads only the ``admin_users`` row of
    the verified identity: no admin record, a missing permission or an empty grant is
    403 with the same generic body. Declaring no or unknown permissions raises at
    import time.
    """
    required = validate_required(permissions)

    async def dependency(
        identity: Annotated[VerifiedIdentity, Depends(get_current_identity)],
        repository: AdminRepositoryDep,
    ) -> AdminContext:
        grant = await repository.get_grant(identity.uid)
        if grant is None:
            logger.warning(
                "admin access denied: no admin record",
                extra={"firebase_uid": identity.uid},
            )
            raise HTTPException(403, FORBIDDEN)
        held = effective_permissions(grant.role, grant.permissions)
        if not required <= held:
            logger.warning(
                "admin access denied: missing permission",
                extra={
                    "admin_user_id": grant.user_id,
                    "firebase_uid": identity.uid,
                    "required": sorted(required),
                },
            )
            raise HTTPException(403, FORBIDDEN)
        return AdminContext(grant.user_id, grant.role, held)

    return dependency


class AdminAuditor:
    """Writes audit rows for an admin request, adding IP, user agent and request id."""

    def __init__(self, service: AuditService, request: Request) -> None:
        self.service, self.request = service, request

    async def record(
        self,
        admin: AdminContext,
        *,
        action: str,
        resource: str,
        resource_id: str | None = None,
        organization_id: str | None = None,
        store_id: str | None = None,
        before: object = None,
        after: object = None,
        details: object = None,
    ) -> None:
        await self.service.record_admin_action(
            admin,
            action=action,
            resource=resource,
            resource_id=resource_id,
            organization_id=organization_id,
            store_id=store_id,
            before=before,
            after=after,
            details=details,
            ip_address=client_ip(self.request),
            user_agent=self.request.headers.get("user-agent"),
            request_id=getattr(self.request.state, "request_id", None),
        )


def get_auditor(request: Request, session: SessionDep) -> AdminAuditor:
    return AdminAuditor(AuditService(AuditRepository(session)), request)


AuditorDep = Annotated[AdminAuditor, Depends(get_auditor)]
