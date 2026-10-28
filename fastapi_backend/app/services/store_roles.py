"""One Postgres role per store database (KAN-238, ADR-005).

Each store database has its own login role, ``store_<store id>`` (the same name as the
database), which owns everything inside it; ``PUBLIC`` loses ``CONNECT`` on it. A store's
connection string therefore opens that store's database only: another store's credential
is refused by Postgres itself, not just by the application's choice of database.

The SQL runs as the provisioning role (the Neon role from ``NEON_ROLE_NAME``, or the
platform role locally). It works without superuser on Postgres 16+, where a role with
CREATEROLE gets ADMIN on the roles it creates but not membership: the explicit
``GRANT <store role> TO CURRENT_USER WITH INHERIT TRUE, SET TRUE`` gives it the
membership that ``ALTER ... OWNER TO <store role>`` and ``REASSIGN OWNED BY
<store role>`` need. The database stays owned by the provisioning role (see
``apply_store_role``).

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
# A store role (and database) name: store_ plus a store id.
STORE_ROLE_PATTERN = re.compile(r"^store_[a-z0-9]{8,40}$")
# 32 random bytes: about 256 bits, far above Neon's 60 bit minimum.
PASSWORD_BYTES = 32
_PASSWORD_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,}$")
# Every function below is schema-qualified, as defence in depth behind the search_path
# that open_admin_connection pins: a store role may create look-alikes in public.
_SYSTEM_SCHEMAS = "n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%'"
# Objects that belong to an extension keep their owner (ALTER EXTENSION has no OWNER).
_NOT_EXTENSION_MEMBER = (
    "NOT EXISTS (SELECT 1 FROM pg_catalog.pg_depend e "
    "WHERE e.classid = {catalog}::pg_catalog.regclass "
    "AND e.objid = {oid} AND e.deptype = 'e')"
)
_ME = "(SELECT oid FROM pg_catalog.pg_roles WHERE rolname = current_user)"
# The advisory lock store_migrations takes per database: role setup and migrations of
# one store never interleave (a migration in between could leave tables on the old owner).
STORE_MIGRATION_LOCK_KEY = 5_735_701
_LOCK = "SELECT pg_catalog.pg_advisory_xact_lock(CAST(:key AS bigint))"
_CURRENT_DATABASE = "SELECT pg_catalog.current_database()"
_ROLE_EXISTS = "SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :role"
# No privileged attribute, a member of no role, and no role but the provisioning role a
# member of it: a re-run must not bless a role someone widened in the meantime.
_ROLE_IS_PLAIN = (
    "SELECT NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication "
    "OR rolbypassrls) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member = r.oid) "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m "
    f"WHERE m.roleid = r.oid AND m.member <> {_ME}) "
    "FROM pg_catalog.pg_roles r WHERE rolname = :role"
)
# One call per privilege: with a list, has_*_privilege is true when ANY is held. A NULL
# datacl means the defaults, where PUBLIC has CONNECT and TEMPORARY.
_ROLE_HAS_ACCESS = (
    "SELECT pg_catalog.has_database_privilege(CAST(:role AS text), "
    "pg_catalog.current_database(), 'CONNECT') "
    "AND pg_catalog.has_database_privilege(CAST(:role AS text), "
    "pg_catalog.current_database(), 'TEMPORARY') "
    "AND pg_catalog.has_schema_privilege(CAST(:role AS text), 'public', 'USAGE') "
    "AND pg_catalog.has_schema_privilege(CAST(:role AS text), 'public', 'CREATE') "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_database d, pg_catalog.aclexplode("
    "COALESCE(d.datacl, pg_catalog.acldefault('d', d.datdba))) a "
    "WHERE d.datname = pg_catalog.current_database() AND a.grantee = 0 "
    "AND a.privilege_type IN ('CONNECT', 'TEMPORARY'))"
)

# Statements generated server-side with format('%I'), so every identifier is quoted by
# Postgres. Each yields "ALTER ... OWNER TO <store role>" for an object the provisioning
# role owns in the current database. Tables carry their indexes, and sequences owned by
# a column move with their table (moving them alone is an error).
_ROLE = "CAST(:role AS text)"
_OWNERSHIP_QUERIES = (
    f"SELECT pg_catalog.format('ALTER SCHEMA %I OWNER TO %I', n.nspname, {_ROLE}) "
    f"FROM pg_catalog.pg_namespace n WHERE n.nspowner = {_ME} AND {_SYSTEM_SCHEMAS} "
    "AND " + _NOT_EXTENSION_MEMBER.format(catalog="'pg_namespace'", oid="n.oid"),
    "SELECT pg_catalog.format('ALTER %s %I.%I OWNER TO %I', CASE c.relkind "
    "WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW' WHEN 'S' THEN 'SEQUENCE' "
    f"WHEN 'f' THEN 'FOREIGN TABLE' ELSE 'TABLE' END, n.nspname, c.relname, {_ROLE}) "
    "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
    "ON n.oid = c.relnamespace "
    f"WHERE c.relowner = {_ME} AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f') "
    f"AND {_SYSTEM_SCHEMAS} AND NOT (c.relkind = 'S' AND EXISTS ("
    "SELECT 1 FROM pg_catalog.pg_depend d "
    "WHERE d.classid = 'pg_catalog.pg_class'::pg_catalog.regclass "
    "AND d.objid = c.oid AND d.refclassid = 'pg_catalog.pg_class'::pg_catalog.regclass "
    "AND d.deptype IN ('a', 'i'))) AND "
    + _NOT_EXTENSION_MEMBER.format(catalog="'pg_class'", oid="c.oid"),
    # A zero-argument aggregate is written name(*); name() is invalid for aggregates.
    "SELECT pg_catalog.format('ALTER %s %I.%I(%s) OWNER TO %I', CASE p.prokind "
    "WHEN 'a' THEN 'AGGREGATE' ELSE 'ROUTINE' END, n.nspname, p.proname, "
    "CASE WHEN p.prokind = 'a' AND pg_catalog.pg_get_function_identity_arguments(p.oid) "
    "= '' THEN '*' ELSE pg_catalog.pg_get_function_identity_arguments(p.oid) END, "
    f"{_ROLE}) "
    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
    "ON n.oid = p.pronamespace "
    f"WHERE p.proowner = {_ME} AND {_SYSTEM_SCHEMAS} AND "
    + _NOT_EXTENSION_MEMBER.format(catalog="'pg_proc'", oid="p.oid"),
    "SELECT pg_catalog.format('ALTER %s %I.%I OWNER TO %I', CASE t.typtype "
    f"WHEN 'd' THEN 'DOMAIN' ELSE 'TYPE' END, n.nspname, t.typname, {_ROLE}) "
    "FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n "
    "ON n.oid = t.typnamespace "
    f"WHERE t.typowner = {_ME} AND {_SYSTEM_SCHEMAS} AND (t.typtype IN ('e', 'd', 'r') "
    "OR (t.typtype = 'c' AND (SELECT relkind FROM pg_catalog.pg_class "
    "WHERE oid = t.typrelid) = 'c')) "
    "AND " + _NOT_EXTENSION_MEMBER.format(catalog="'pg_type'", oid="t.oid"),
)
# Anything the provisioning role still owns in this database after the moves above.
# Left out: extensions and their members (they cannot change owner and keep working)
# and default privileges (pg_default_acl entries own nothing a store uses).
_LEFTOVER_OWNED = (
    "SELECT pg_catalog.count(*) FROM pg_catalog.pg_shdepend s "
    f"WHERE s.refobjid = {_ME} AND s.deptype = 'o' "
    "AND s.refclassid = 'pg_catalog.pg_authid'::pg_catalog.regclass "
    "AND s.classid <> 'pg_catalog.pg_extension'::pg_catalog.regclass "
    "AND s.classid <> 'pg_catalog.pg_default_acl'::pg_catalog.regclass "
    "AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_depend e WHERE e.classid = s.classid "
    "AND e.objid = s.objid AND e.deptype = 'e') "
    "AND s.dbid = (SELECT oid FROM pg_catalog.pg_database "
    "WHERE datname = pg_catalog.current_database())"
)


class UnsafeRoleInput(ValueError):
    """A role name or password failed validation. The message never carries the value."""


class StoreRoleError(Exception):
    """The store role SQL ran but its result is not the expected one. No secrets."""


class StoreRoleCheckFailed(StoreRoleError):
    """The role holds a privileged attribute or membership, or lacks its access."""


class OwnershipNotMoved(StoreRoleError):
    """Objects the provisioning role owns remain in the store database (``count``)."""

    def __init__(self, count: int) -> None:
        super().__init__(f"{count} object(s) still owned by the provisioning role")
        self.count = count


def new_role_password() -> str:
    return secrets.token_urlsafe(PASSWORD_BYTES)


def _identifier(name: str) -> str:
    if not STORE_ROLE_PATTERN.fullmatch(name):
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


async def _enter_store_database(connection: AsyncConnection, name: str) -> None:
    """Refuse any other database, then wait for the store's migration lock."""
    current = await connection.scalar(text(_CURRENT_DATABASE))
    if current != name:
        raise UnsafeRoleInput("not connected to the store database")
    # Transaction scoped (re-entrant); bounded by the admin connection's lock_timeout.
    await connection.scalar(text(_LOCK), {"key": STORE_MIGRATION_LOCK_KEY})


async def _check(connection: AsyncConnection, query: str, name: str, what: str) -> None:
    if await connection.scalar(text(query), {"role": name}) is not True:
        raise StoreRoleCheckFailed(what)


async def apply_store_role(
    connection: AsyncConnection, name: str, password: str
) -> int:
    """Make the role ``name`` the only non-admin user of the database ``name``.

    Run in one transaction as the provisioning role, connected to the store database
    itself. Creates the role (or, on a re-run, only sets its new password, so the
    previous connection string stops working), shuts PUBLIC out, grants the role
    CONNECT and TEMPORARY on the database and USAGE and CREATE on ``public``, and hands
    it every object the provisioning role owns there. Then it checks the result
    (no privileged attribute or membership, the access granted, PUBLIC shut out) and
    raises StoreRoleCheckFailed otherwise, so the transaction rolls back. Returns the
    number of objects whose owner changed (0 for a new database).

    The database itself stays owned by the provisioning role. Neon's control plane
    records that role as the owner and may set it back, and a grant from an owner to
    itself merges into the owner's own entry and follows ownership: access granted by
    a different owner does not depend on it. The store role cannot alter or drop its
    database, only use it; it owns everything inside.
    """
    quoted = _identifier(name)
    literal = _password_literal(password)
    await _enter_store_database(connection, name)
    exists = await connection.scalar(text(_ROLE_EXISTS), {"role": name})
    verb = "ALTER" if exists else "CREATE"
    # SUPERUSER, REPLICATION and the like are not named: a CREATEROLE non-superuser may
    # not even name them in ALTER ROLE, CREATE ROLE defaults to none of them, and the
    # check below refuses a role that has any. The rest is reset on every run.
    await connection.exec_driver_sql(
        f"{verb} ROLE {quoted} WITH LOGIN CONNECTION LIMIT -1 "
        f"VALID UNTIL 'infinity' PASSWORD {literal}"
    )
    await connection.exec_driver_sql(f"ALTER ROLE {quoted} RESET ALL")
    await connection.exec_driver_sql(
        f"ALTER ROLE {quoted} IN DATABASE {quoted} RESET ALL"
    )
    await _check(
        connection, _ROLE_IS_PLAIN, name, "store role is not a plain login role"
    )
    # Explicit options, so a NOINHERIT provisioning role still gets both: SET to give the
    # role objects and to drop it, INHERIT to use its database for repairs.
    await connection.exec_driver_sql(
        f"GRANT {quoted} TO CURRENT_USER WITH INHERIT TRUE, SET TRUE"
    )
    await connection.exec_driver_sql(
        f"REVOKE CONNECT, TEMPORARY ON DATABASE {quoted} FROM PUBLIC"
    )
    await connection.exec_driver_sql(
        f"GRANT CONNECT, TEMPORARY ON DATABASE {quoted} TO {quoted}"
    )
    await connection.exec_driver_sql(
        f"GRANT USAGE, CREATE ON SCHEMA public TO {quoted}"
    )
    moved = await move_owned_objects(connection, name)
    # A GRANT or REVOKE that cannot apply (for example when someone else owns the
    # database or public) only warns; fail here rather than at the next migration.
    await verify_store_access(connection, name)
    return moved


async def verify_store_access(connection: AsyncConnection, name: str) -> None:
    """Raise StoreRoleCheckFailed unless the role has all its access and PUBLIC none."""
    _identifier(name)
    await _check(connection, _ROLE_HAS_ACCESS, name, "store role access not in place")


async def move_owned_objects(connection: AsyncConnection, name: str) -> int:
    """Give the role ``name`` every object the provisioning role owns in its database.

    A new database has none; a store built before KAN-238 (backfill, or an orphan
    database reused by a re-provision) has its whole schema. Never ``REASSIGN OWNED``:
    that would also move every other database the shared role owns. Raises
    OwnershipNotMoved when anything is left behind, so the caller rolls back.
    Returns the number of ALTER statements run.
    """
    _identifier(name)
    await _enter_store_database(connection, name)
    statements: list[str] = []
    for query in _OWNERSHIP_QUERIES:
        rows = await connection.execute(text(query), {"role": name})
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


async def release_store_database(connection: AsyncConnection, name: str) -> None:
    """Hand the database back to the provisioning role and drop the store role.

    Run connected to the store database itself, just before it is deleted, where the
    database cannot be dropped first (Neon). ``REASSIGN OWNED BY`` the *store* role is
    safe: that role owns nothing outside this database.
    """
    quoted = _identifier(name)
    exists = await connection.scalar(text(_ROLE_EXISTS), {"role": name})
    if not exists:
        return
    await connection.exec_driver_sql(f"REASSIGN OWNED BY {quoted} TO CURRENT_USER")
    await connection.exec_driver_sql(f"DROP OWNED BY {quoted}")
    await connection.exec_driver_sql(f"DROP ROLE {quoted}")
