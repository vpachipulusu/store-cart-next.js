"""One Postgres role per store database (KAN-238, ADR-005).

Each store database is owned by its own login role, ``store_<store id>`` (the same name
as the database), and ``PUBLIC`` loses ``CONNECT`` on it. A store's connection string
therefore opens that store's database only: another store's credential is refused by
Postgres itself, not just by the application's choice of database.

The SQL runs as the provisioning role (the Neon role from ``NEON_ROLE_NAME``, or the
platform role locally). It works without superuser on Postgres 16+, where a role with
CREATEROLE gets ADMIN on the roles it creates but not membership: the explicit
``GRANT <store role> TO CURRENT_USER`` gives it the SET (and, for a normal INHERIT role,
inherited) membership that ``ALTER DATABASE ... OWNER TO`` needs.

DDL cannot take bind parameters, so identifiers are checked against a strict pattern and
quoted, and the password is generated here from a URL-safe alphabet, checked against that
alphabet and quoted as a literal. Neon refuses pre-hashed passwords, so the literal is the
plaintext: it is never logged, and no function here puts SQL text in an exception.
"""

import re
import secrets

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection

STORE_NAME_PREFIX = "store_"
# 32 random bytes: about 256 bits, far above Neon's 60 bit minimum.
PASSWORD_BYTES = 32
_NAME_PATTERN = re.compile(r"^store_[a-z0-9]{8,40}$")
_PASSWORD_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,}$")
_SYSTEM_SCHEMAS = "n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%'"
# Objects that belong to an extension keep their owner (ALTER EXTENSION has no OWNER).
_NOT_EXTENSION_MEMBER = (
    "NOT EXISTS (SELECT 1 FROM pg_depend e WHERE e.classid = {catalog}::regclass "
    "AND e.objid = {oid} AND e.deptype = 'e')"
)
_ME = "(SELECT oid FROM pg_roles WHERE rolname = current_user)"

# Statements generated server-side with format('%I'), so every identifier is quoted by
# Postgres. Each yields "ALTER ... OWNER TO <store role>" for an object the provisioning
# role owns in the current database. Tables carry their indexes, and sequences owned by
# a column move with their table (moving them alone is an error).
_OWNERSHIP_QUERIES = (
    "SELECT format('ALTER SCHEMA %I OWNER TO %I', n.nspname, CAST(:role AS text)) "
    f"FROM pg_namespace n WHERE n.nspowner = {_ME} AND {_SYSTEM_SCHEMAS} AND "
    + _NOT_EXTENSION_MEMBER.format(catalog="'pg_namespace'", oid="n.oid"),
    "SELECT format('ALTER %s %I.%I OWNER TO %I', CASE c.relkind "
    "WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW' WHEN 'S' THEN 'SEQUENCE' "
    "WHEN 'f' THEN 'FOREIGN TABLE' ELSE 'TABLE' END, n.nspname, c.relname, CAST(:role AS text)) "
    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    f"WHERE c.relowner = {_ME} AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f') "
    f"AND {_SYSTEM_SCHEMAS} AND NOT (c.relkind = 'S' AND EXISTS ("
    "SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass "
    "AND d.objid = c.oid AND d.refclassid = 'pg_class'::regclass "
    "AND d.deptype IN ('a', 'i'))) AND "
    + _NOT_EXTENSION_MEMBER.format(catalog="'pg_class'", oid="c.oid"),
    "SELECT format('ALTER %s %I.%I(%s) OWNER TO %I', CASE p.prokind "
    "WHEN 'a' THEN 'AGGREGATE' ELSE 'ROUTINE' END, n.nspname, p.proname, "
    "pg_get_function_identity_arguments(p.oid), CAST(:role AS text)) "
    "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
    f"WHERE p.proowner = {_ME} AND {_SYSTEM_SCHEMAS} AND "
    + _NOT_EXTENSION_MEMBER.format(catalog="'pg_proc'", oid="p.oid"),
    "SELECT format('ALTER %s %I.%I OWNER TO %I', CASE t.typtype "
    "WHEN 'd' THEN 'DOMAIN' ELSE 'TYPE' END, n.nspname, t.typname, CAST(:role AS text)) "
    "FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
    f"WHERE t.typowner = {_ME} AND {_SYSTEM_SCHEMAS} AND (t.typtype IN ('e', 'd', 'r') "
    "OR (t.typtype = 'c' AND (SELECT relkind FROM pg_class WHERE oid = t.typrelid) = 'c')) "
    "AND " + _NOT_EXTENSION_MEMBER.format(catalog="'pg_type'", oid="t.oid"),
)
# Anything the provisioning role still owns in this database after the moves above.
# Extensions are left out: they cannot change owner and keep working as they are.
_LEFTOVER_OWNED = (
    "SELECT count(*) FROM pg_shdepend "
    f"WHERE refobjid = {_ME} AND deptype = 'o' "
    "AND classid <> 'pg_extension'::regclass "
    "AND dbid = (SELECT oid FROM pg_database WHERE datname = current_database())"
)


class UnsafeRoleInput(ValueError):
    """A role name or password failed validation. The message never carries the value."""


class OwnershipNotMoved(Exception):
    """Objects the provisioning role owns remain in the store database (``count``)."""

    def __init__(self, count: int) -> None:
        super().__init__(f"{count} object(s) still owned by the provisioning role")
        self.count = count


def new_role_password() -> str:
    return secrets.token_urlsafe(PASSWORD_BYTES)


def _identifier(name: str) -> str:
    if not _NAME_PATTERN.fullmatch(name):
        raise UnsafeRoleInput("invalid store role or database name")
    return f'"{name}"'


def _password_literal(password: str) -> str:
    if not _PASSWORD_PATTERN.fullmatch(password):
        raise UnsafeRoleInput("invalid generated password")
    # The alphabet has no quote or backslash; doubling quotes is belt and braces.
    return "'" + password.replace("'", "''") + "'"


def with_role(connection_string: str, role: str, password: str) -> str:
    """The same server, database and options, signed in as ``role``. A secret."""
    return (
        make_url(connection_string)
        .set(username=role, password=password)
        .render_as_string(hide_password=False)
    )


async def apply_store_role(
    connection: AsyncConnection, role: str, database: str, password: str
) -> None:
    """Create (or re-password) the store role and make it the database's only user.

    Run inside one transaction as the provisioning role. Idempotent: on a re-run the
    role keeps its objects and only its password changes, so the previous connection
    string stops working.
    """
    quoted_role, quoted_database = _identifier(role), _identifier(database)
    literal = _password_literal(password)
    exists = await connection.scalar(
        text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
    )
    verb = "ALTER" if exists else "CREATE"
    # Only LOGIN and PASSWORD are set: a CREATEROLE non-superuser may not even name
    # SUPERUSER or REPLICATION in ALTER ROLE, and CREATE ROLE defaults to none of them.
    await connection.exec_driver_sql(
        f"{verb} ROLE {quoted_role} WITH LOGIN PASSWORD {literal}"
    )
    await connection.exec_driver_sql(f"GRANT {quoted_role} TO CURRENT_USER")
    await connection.exec_driver_sql(
        f"ALTER DATABASE {quoted_database} OWNER TO {quoted_role}"
    )
    await connection.exec_driver_sql(
        f"REVOKE CONNECT, TEMPORARY ON DATABASE {quoted_database} FROM PUBLIC"
    )


async def move_owned_objects(connection: AsyncConnection, role: str) -> int:
    """Give ``role`` every object the provisioning role owns in the current database.

    Backfill only (existing stores built under the shared role). Never ``REASSIGN
    OWNED``: that would also move every other database the shared role owns. Raises
    OwnershipNotMoved when anything is left behind, so the caller rolls back.
    Returns the number of ALTER statements run.
    """
    _identifier(role)
    statements: list[str] = []
    for query in _OWNERSHIP_QUERIES:
        rows = await connection.execute(text(query), {"role": role})
        statements.extend(row[0] for row in rows)
    for statement in statements:
        await connection.exec_driver_sql(statement)
    leftover = int(await connection.scalar(text(_LEFTOVER_OWNED)) or 0)
    if leftover:
        raise OwnershipNotMoved(leftover)
    return len(statements)


async def drop_store_role(connection: AsyncConnection, role: str) -> None:
    """Drop the role once its database is gone (no-op when absent)."""
    await connection.exec_driver_sql(f"DROP ROLE IF EXISTS {_identifier(role)}")


async def release_store_database(
    connection: AsyncConnection, role: str, database: str
) -> None:
    """Hand the database back to the provisioning role and drop the store role.

    Run connected to the store database itself, just before it is deleted, where the
    database cannot be dropped first (Neon). ``REASSIGN OWNED BY`` the *store* role is
    safe: that role owns nothing outside this database.
    """
    quoted_role = _identifier(role)
    _identifier(database)
    exists = await connection.scalar(
        text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
    )
    if not exists:
        return
    await connection.exec_driver_sql(f"REASSIGN OWNED BY {quoted_role} TO CURRENT_USER")
    await connection.exec_driver_sql(f"DROP OWNED BY {quoted_role}")
    await connection.exec_driver_sql(f"DROP ROLE {quoted_role}")
