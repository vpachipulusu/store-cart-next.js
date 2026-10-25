"""Move existing stores onto their own database role (KAN-238, ADR-005).

Stores provisioned before KAN-238 connect as the shared provisioning role. For each
store, ``backfill_store_role`` creates ``store_<id>``, makes it the owner of the store
database and of every object the shared role owns in it (including the store Alembic
version table), revokes PUBLIC's CONNECT, and re-encrypts the new connection string onto
the store row. ``commands.backfill_store_roles`` is its command line; it is an owner step,
run once per environment, never from a request or a deploy.

* The admin connection uses the store's current (shared role) string, switched to the
  direct endpoint. The DDL runs in one transaction, so a store is moved entirely or not
  at all; anything left owned by the shared role rolls it back (``OwnershipNotMoved``).
* The store row stays locked while its database is changed. If the platform commit fails
  after the DDL committed, the store keeps working on the old string (the shared role is
  a member of the store role) and a re-run finishes it.
* A store already on its own role is skipped, so a re-run is safe.
* Reports carry store ids and exception class names only, never a connection string.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.core.database import (
    DefaultSessionProvider,
    SessionProvider,
    async_session_maker,
)
from app.models.platform.store import Store
from app.services import store_secrets
from app.services.store_migrations import safe_reason
from app.services.store_provisioning import AdminConnection, database_name_for
from app.services.store_roles import (
    apply_store_role,
    move_owned_objects,
    new_role_password,
    with_role,
)
from app.services.store_sessions import (
    StoreDatabaseNotConfigured,
    StoreDatabaseUnavailable,
    StoreNotFound,
    open_admin_connection,
)

logger = logging.getLogger("storecart.store_role_backfill")

_POOLER_SUFFIX = "-pooler"


@dataclass(frozen=True)
class BackfillReport:
    moved: tuple[str, ...] = ()
    # Stores already on their own role, or with no database yet.
    skipped: tuple[str, ...] = ()
    failed_store_id: str | None = None
    failure_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.failed_store_id is None


def direct_endpoint(connection_string: str) -> str:
    """Neon's unpooled host for a pooled string (``ep-x-pooler.…`` → ``ep-x.…``)."""
    url = make_url(connection_string)
    host = url.host or ""
    first, dot, rest = host.partition(".")
    if not first.endswith(_POOLER_SUFFIX):
        return connection_string
    direct = f"{first.removesuffix(_POOLER_SUFFIX)}{dot}{rest}"
    return url.set(host=direct).render_as_string(hide_password=False)


async def backfill_store_role(
    store_id: str,
    provider: SessionProvider,
    admin_connection: AdminConnection = open_admin_connection,
) -> bool:
    """Move one store onto its own role. False when there was nothing to do."""
    name = database_name_for(store_id)
    async with provider.session() as session:
        store = (
            await session.execute(
                select(Store).where(Store.id == store_id).with_for_update()
            )
        ).scalar_one_or_none()
        if store is None:
            raise StoreNotFound(store_id)
        current = store_secrets.reveal_connection_string(store)
        if current is None:
            raise StoreDatabaseNotConfigured(store_id)
        url = make_url(current)
        if url.username == name:
            return False
        if url.database != name:
            raise StoreDatabaseUnavailable(store_id)
        password = new_role_password()
        async with admin_connection(direct_endpoint(current)) as connection:
            await apply_store_role(connection, name, name, password)
            moved = await move_owned_objects(connection, name)
        store_secrets.set_connection_string(store, with_role(current, name, password))
        await session.commit()
    logger.info(
        "store moved to its own database role",
        extra={"store_id": store_id, "objects": moved},
    )
    return True


async def backfill_store_roles(
    provider: SessionProvider | None = None,
    *,
    store_ids: Sequence[str] | None = None,
    admin_connection: AdminConnection = open_admin_connection,
) -> BackfillReport:
    """Every store with a connection string (or ``store_ids``), in id order.

    Stops at the first failure; later stores are untouched.
    """
    provider = provider or DefaultSessionProvider(async_session_maker)
    if store_ids is None:
        async with provider.session() as session:
            store_ids = list(
                (
                    await session.execute(
                        select(Store.id)
                        .where(Store.connection_string_encrypted.is_not(None))
                        .order_by(Store.id)
                    )
                ).scalars()
            )
    moved: list[str] = []
    skipped: list[str] = []
    for store_id in store_ids:
        try:
            changed = await backfill_store_role(store_id, provider, admin_connection)
        except StoreDatabaseNotConfigured:
            skipped.append(store_id)
            continue
        except Exception as exc:  # noqa: BLE001 - reported per store, never raised
            reason = safe_reason(exc)
            logger.error(
                "store role backfill failed: %s", reason, extra={"store_id": store_id}
            )
            return BackfillReport(tuple(moved), tuple(skipped), store_id, reason)
        (moved if changed else skipped).append(store_id)
    return BackfillReport(tuple(moved), tuple(skipped))
