from app.repositories.storefront import PublicStore
from app.services.storefront import StorefrontService

ACME = PublicStore(name="Acme", slug="acme")


class FakeReader:
    def __init__(self) -> None:
        self.lookups: list[str] = []

    async def find_active_by_slug(self, slug: str) -> PublicStore | None:
        self.lookups.append(slug)
        return ACME if slug == "acme" else None


async def test_lookup_normalises_case_before_querying() -> None:
    reader = FakeReader()

    result = await StorefrontService(reader).lookup("AcMe")

    assert result == ACME
    assert reader.lookups == ["acme"]


async def test_lookup_returns_none_for_unknown_slug() -> None:
    assert await StorefrontService(FakeReader()).lookup("nope-shop") is None


async def test_invalid_and_reserved_slugs_never_reach_the_repository() -> None:
    reader = FakeReader()
    service = StorefrontService(reader)

    results = [
        await service.lookup(s) for s in ("ab", "a--b", "acmé", "www", "x" * 200)
    ]

    assert results == [None] * 5
    assert reader.lookups == []
