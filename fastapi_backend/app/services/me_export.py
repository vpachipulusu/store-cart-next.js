"""Personal data export (KAN-120): collect the caller's own data and audit the download.

The audit row and the reads share one transaction and one commit, so a download is never
served without its audit entry: if the audit write fails the export fails.
"""

from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.me_export import AccountExport
from app.services.audit import AuditWriter

EXPORT_ACTION = "me.export"
EXPORT_RESOURCE = "user"


class ExportNotAvailable(Exception):
    """The user row vanished (for example the account was just deleted)."""


class ExportRepository(Protocol):
    async def user_id_for_uid(self, uid: str) -> str | None: ...
    async def collect(self, user_id: str) -> AccountExport | None: ...


class MeExportService:
    def __init__(
        self, repository: ExportRepository, audit: AuditWriter, session: AsyncSession
    ) -> None:
        self.repository, self.audit, self.session = repository, audit, session

    async def export(
        self,
        uid: str,
        *,
        ip_address: str | None,
        user_agent: str | None,
        request_id: str | None,
    ) -> AccountExport:
        try:
            export = await self._collect_and_audit(
                uid, ip_address, user_agent, request_id
            )
        except Exception:
            await self.session.rollback()
            raise
        await self.session.commit()
        return export

    async def _collect_and_audit(
        self,
        uid: str,
        ip_address: str | None,
        user_agent: str | None,
        request_id: str | None,
    ) -> AccountExport:
        user_id = await self.repository.user_id_for_uid(uid)
        export = await self.repository.collect(user_id) if user_id else None
        if user_id is None or export is None:
            raise ExportNotAvailable()
        # Counts only: the audit trail must not hold a second copy of the personal data.
        details: dict[str, Any] = {
            "memberships": len(export.memberships),
            "login_history": len(export.login_history),
            "notifications": len(export.notifications),
            "truncated": export.truncated,
        }
        if request_id is not None:
            details["request_id"] = request_id
        await self.audit.add(
            user_id=user_id,
            organization_id=None,
            action=EXPORT_ACTION,
            resource=EXPORT_RESOURCE,
            resource_id=user_id,
            metadata={"actor_role": "self", "details": details},
            ip_address=ip_address,
            user_agent=user_agent[:512] if user_agent else None,
        )
        return export
