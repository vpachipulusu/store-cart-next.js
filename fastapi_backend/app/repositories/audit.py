from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform.audit_log import AuditLog


class AuditRepository:
    """Append only: there is deliberately no update or delete here."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
    ) -> None:
        """Stage the row in the caller's transaction; the caller commits."""
        self.session.add(
            AuditLog(
                user_id=user_id,
                organization_id=organization_id,
                action=action,
                resource=resource,
                resource_id=resource_id,
                metadata_=metadata,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        await self.session.flush()
