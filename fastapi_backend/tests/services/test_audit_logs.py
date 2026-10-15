import pytest

from app.repositories.audit import AuditFilters, AuditPage
from app.services.audit_logs import MAX_PAGE_SIZE, AuditLogsService


class Reader:
    def __init__(self) -> None:
        self.calls: list[tuple[AuditFilters, int, int]] = []

    async def list_entries(
        self, filters: AuditFilters, limit: int, offset: int
    ) -> AuditPage:
        self.calls.append((filters, limit, offset))
        return AuditPage([], 0)


@pytest.mark.parametrize(
    ("limit", "offset", "expected"),
    [(10, 5, (10, 5)), (0, -3, (1, 0)), (10_000, 0, (MAX_PAGE_SIZE, 0))],
)
async def test_page_bounds_are_clamped(limit, offset, expected):
    reader = Reader()
    filters = AuditFilters(organization_id="o1")

    await AuditLogsService(reader).list_entries(filters, limit, offset)

    assert reader.calls == [(filters, *expected)]
