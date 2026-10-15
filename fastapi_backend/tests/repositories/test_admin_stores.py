import pytest

from app.repositories.admin_stores import _escape_like

BACKSLASH = chr(92)


@pytest.mark.parametrize(
    ("term", "escaped"),
    [
        ("plain", "plain"),
        ("50%", "50" + BACKSLASH + "%"),
        ("a_b", "a" + BACKSLASH + "_b"),
        ("a" + BACKSLASH + "b", "a" + BACKSLASH * 2 + "b"),
    ],
)
def test_like_wildcards_and_backslashes_are_escaped(term, escaped):
    assert _escape_like(term) == escaped


def _organizations_sql(search: str | None = None) -> str:
    from sqlalchemy.dialects import postgresql

    from app.repositories.admin_stores import (
        _organization_match,
        organizations_statement,
    )

    statement = organizations_statement(_organization_match(search), 20, 40)
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_organizations_are_paged_before_their_stores_are_counted():
    sql = _organizations_sql()

    inner = sql[sql.index("FROM organizations") :]
    page_end = sql.index(") AS page")
    assert sql.count("LIMIT") == 1
    assert sql.index("LIMIT 20 OFFSET 40") < page_end  # paging is inside the subquery
    # the store count is correlated to the page rows and sits in the select list
    assert sql.index("WHERE stores.organization_id = page.id") < sql.index("FROM org")
    assert "GROUP BY" not in sql
    assert "JOIN" not in sql
    assert "ORDER BY organizations.created_at DESC, organizations.id" in inner
    assert sql.rstrip().endswith("ORDER BY page.created_at DESC, page.id")


def test_organization_search_filters_the_page_not_the_store_count():
    sql = _organizations_sql("acme")

    page = sql[sql.index("FROM organizations") : sql.index("LIMIT")]
    assert "organizations.name" in page and "organizations.slug" in page
    assert "LIKE" in page.upper() and "ESCAPE" in page.upper()
