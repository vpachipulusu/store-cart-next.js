from app.core.db_url import to_async_target


def test_rewrites_the_driver_to_asyncpg():
    target = to_async_target("postgresql://user:pw@localhost:5432/app")

    assert target.url.drivername == "postgresql+asyncpg"
    assert target.url.host == "localhost"
    assert target.url.port == 5432
    assert target.url.database == "app"
    assert target.connect_args == {}


def test_keeps_the_password_even_with_special_characters():
    target = to_async_target("postgresql://user:p%40ss%2Fw@host/app")

    assert target.url.password == "p@ss/w"


def test_passes_sslmode_through_as_the_asyncpg_ssl_argument():
    target = to_async_target(
        "postgresql://user:pw@ep-x.neon.tech/app?sslmode=require&channel_binding=require"
    )

    assert target.connect_args == {"ssl": "require"}
    assert dict(target.url.query) == {}


def test_accepts_an_asyncpg_url_with_ssl_parameter():
    target = to_async_target("postgresql+asyncpg://u:p@h/app?ssl=verify-full")

    assert target.url.drivername == "postgresql+asyncpg"
    assert target.connect_args == {"ssl": "verify-full"}
