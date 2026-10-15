from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
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
        store_id: str | None = None,
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
                store_id=store_id,
                action=action,
                resource=resource,
                resource_id=resource_id,
                metadata_=metadata,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        await self.session.flush()


@dataclass(frozen=True)
class AuditEntry:
    id: str
    created_at: datetime
    user_id: str | None
    organization_id: str | None
    store_id: str | None
    action: str
    resource: str
    resource_id: str | None
    metadata: Any
    ip_address: str | None
    user_agent: str | None


@dataclass(frozen=True)
class AuditFilters:
    organization_id: str | None = None
    store_id: str | None = None
    user_id: str | None = None
    action: str | None = None


@dataclass(frozen=True)
class AuditPage:
    entries: list[AuditEntry]
    total_count: int


class AuditReader:
    """Read side for the admin list. Never writes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_entries(
        self, filters: AuditFilters, limit: int, offset: int
    ) -> AuditPage:
        conditions = [
            column == value
            for column, value in (
                (AuditLog.organization_id, filters.organization_id),
                (AuditLog.store_id, filters.store_id),
                (AuditLog.user_id, filters.user_id),
                (AuditLog.action, filters.action),
            )
            if value is not None
        ]
        total = await self.session.scalar(
            select(func.count()).select_from(AuditLog).where(*conditions)
        )
        rows = await self.session.scalars(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return AuditPage(
            [
                AuditEntry(
                    id=row.id,
                    created_at=row.created_at,
                    user_id=row.user_id,
                    organization_id=row.organization_id,
                    store_id=row.store_id,
                    action=row.action,
                    resource=row.resource,
                    resource_id=row.resource_id,
                    metadata=row.metadata_,
                    ip_address=row.ip_address,
                    user_agent=row.user_agent,
                )
                for row in rows
            ],
            total or 0,
        )
