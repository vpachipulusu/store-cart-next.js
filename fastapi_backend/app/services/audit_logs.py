"""Platform admin audit log listing (KAN-49). Read only: listing writes no audit row."""

from typing import Protocol

from app.repositories.audit import AuditFilters, AuditPage

MAX_PAGE_SIZE = 100


class AuditLogReader(Protocol):
    async def list_entries(
        self, filters: AuditFilters, limit: int, offset: int
    ) -> AuditPage: ...


class AuditLogsService:
    def __init__(self, reader: AuditLogReader) -> None:
        self.reader = reader

    async def list_entries(
        self, filters: AuditFilters, limit: int, offset: int
    ) -> AuditPage:
        return await self.reader.list_entries(
            filters, min(max(limit, 1), MAX_PAGE_SIZE), max(offset, 0)
        )
