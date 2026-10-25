"""Validation and quoting in store_roles (KAN-238); the SQL itself runs in *_e2e."""

import pytest
from sqlalchemy.engine import make_url

from app.services import store_roles
from app.services.store_roles import (
    OwnershipNotMoved,
    UnsafeRoleInput,
    apply_store_role,
    drop_store_role,
    move_owned_objects,
    new_role_password,
    release_store_database,
    with_role,
)
from tests.fakes_provisioning import FakeEngine

ROLE = "store_clx1abcd2efgh3ijkl4mnop5"


def test_passwords_are_long_url_safe_and_unique():
    first, second = new_role_password(), new_role_password()

    assert first != second
    assert len(first) >= 43
    assert set(first) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )


def test_with_role_keeps_host_database_and_options():
    source = "postgresql://owner:old@ep-x-pooler.neon.tech/store_a?sslmode=require"

    url = make_url(with_role(source, "store_a", "n3w-secret"))

    assert (url.username, url.password) == ("store_a", "n3w-secret")
    assert (url.host, url.database) == ("ep-x-pooler.neon.tech", "store_a")
    assert url.query == {"sslmode": "require"}


@pytest.mark.parametrize(
    "role",
    ['store_x"; DROP ROLE postgres; --', "postgres", "store_UPPER12345", "store_a"],
)
async def test_unsafe_names_are_refused_before_any_statement(role: str):
    engine = FakeEngine()

    with pytest.raises(UnsafeRoleInput) as caught:
        await apply_store_role(
            engine.begin(),  # type: ignore[arg-type]
            role,
            role,
            new_role_password(),
        )
    for call in (drop_store_role, move_owned_objects):
        with pytest.raises(UnsafeRoleInput):
            await call(engine.begin(), role)  # type: ignore[arg-type]
    with pytest.raises(UnsafeRoleInput):
        await release_store_database(engine.begin(), role, role)  # type: ignore[arg-type]

    assert engine.statements == []
    assert role not in str(caught.value)


@pytest.mark.parametrize("password", ["short", "has'quote" * 8, "space " * 10])
async def test_unsafe_passwords_are_refused_without_echoing_them(password: str):
    engine = FakeEngine()

    with pytest.raises(UnsafeRoleInput) as caught:
        await apply_store_role(engine.begin(), ROLE, ROLE, password)  # type: ignore[arg-type]

    assert password not in str(caught.value)
    assert engine.statements == []


def test_ownership_error_carries_only_a_count():
    error = OwnershipNotMoved(3)

    assert error.count == 3
    assert str(error) == "3 object(s) still owned by the provisioning role"


def test_ownership_queries_quote_identifiers_server_side():
    for query in store_roles._OWNERSHIP_QUERIES:
        assert "format('ALTER" in query
        assert "%I" in query
        assert "CAST(:role AS text)" in query
    assert "REASSIGN" not in " ".join(store_roles._OWNERSHIP_QUERIES)
