from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.engine import URL, make_url

ASYNC_DRIVER = "postgresql+asyncpg"

# Query parameters that asyncpg understands as connect arguments. libpq-style
# `sslmode` is translated to asyncpg's `ssl`; every other parameter (for example
# `channel_binding`, `options`) is dropped because asyncpg rejects it.
_TLS_PARAMS = ("ssl", "sslmode")

# Neon pooled endpoints sit behind PgBouncer in transaction mode, which cannot keep
# asyncpg's server-side prepared statements, so the statement cache is off.
STATEMENT_CACHE_SIZE = 0

# Seconds asyncpg waits to open a connection before raising TimeoutError (its
# default is 60). Long enough for a Neon compute to wake from suspend.
CONNECT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class AsyncDatabaseTarget:
    """An asyncpg URL (password intact) and its connect args.

    The connect args carry the TLS mode, the disabled statement cache and the connect
    timeout. The app engines (``build_engine``) and Alembic both use them.
    """

    url: URL
    connect_args: dict[str, Any] = field(default_factory=dict)


def to_async_target(raw_url: str) -> AsyncDatabaseTarget:
    """Rebuild a Postgres URL for asyncpg without losing TLS settings.

    Accepts `postgresql://`, `postgres://` or `postgresql+asyncpg://`, with or
    without `?sslmode=require` (the form Neon hands out).
    """
    parsed = make_url(raw_url)
    tls_mode = next(
        (str(parsed.query[key]) for key in _TLS_PARAMS if key in parsed.query), None
    )
    url = parsed.set(drivername=ASYNC_DRIVER, query={})
    tls_args: dict[str, Any] = {} if tls_mode is None else {"ssl": tls_mode}
    connect_args: dict[str, Any] = {
        "statement_cache_size": STATEMENT_CACHE_SIZE,
        "timeout": CONNECT_TIMEOUT_SECONDS,
        **tls_args,
    }
    return AsyncDatabaseTarget(url=url, connect_args=connect_args)
