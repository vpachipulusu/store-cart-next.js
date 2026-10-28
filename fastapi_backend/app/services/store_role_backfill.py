"""Move existing stores onto their own database role (KAN-238, ADR-005).

Stores provisioned before KAN-238 connect as the shared provisioning role. For each
store, ``backfill_store_role`` runs the provisioning SQL (``apply_store_role``): it creates
``store_<id>``, revokes PUBLIC's CONNECT, grants the role access, and gives it every
object the shared role owns in the store database (including the store Alembic version
table); then it re-encrypts the new connection string onto the store row.
``commands.backfill_store_roles`` is its command line; it is an owner step, run once per
environment with ``migrate_stores`` and provisioning paused, never from a request or a
deploy. Afterwards the shared role's password must be reset (ADR-005): every string
written before KAN-238 still carries it.

* The admin connection uses the store's current (shared role) string, switched to the
  direct endpoint. The DDL runs in one transaction under the store's migration advisory
  lock, so a store is moved entirely or not at all; anything left owned by the shared role
  rolls it back (``OwnershipNotMoved``).
* The store row stays locked while its database is changed. If the platform commit fails
  after the DDL committed, the store keeps working on the old string (the shared role is
  a member of the store role) and a re-run finishes it.
* After the row flips, ownership is moved once more: a migration that ran on the old
  string between the DDL commit and the flip may have created tables as the shared role.
* A store already on its own role is checked again: anything the shared role still owns
  in its database (a failed or raced post-flip pass) is moved, over the provisioning
  role's own direct string from the provisioner (so a re-run needs the same
  STORE_DB_PROVIDER and NEON_* settings as provisioning), and the store counts as moved;
  with nothing to move it is skipped, so a re-run is safe. That string is fetched before
  any platform row is locked. ``dry_run`` checks and lists without changing anything
  (``would repair`` for a moved store with objects left behind).
* Reports carry store ids and exception class names only, never a connection string.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.database import (
    DefaultSessionProvider,
    SessionProvider,
    async_session_maker,
)
from app.models.platform.store import Store, StoreStatus
from app.services import store_secrets
from app.services.store_migrations import safe_reason
from app.services.store_provisioning import (
    AdminConnection,
    database_name_for,
    get_database_provisioner,
)
from app.services.store_roles import (
    StoreRoleError,
    apply_store_role,
    count_leftover_owned,
    describe_failure,
    move_owned_objects,
    new_role_password,
    with_role,
)
from app.services.store_sessions import (
    StoreDatabaseUnavailable,
    StoreNotFound,
    open_admin_connection,
)

logger = logging.getLogger("storecart.store_role_backfill")

_POOLER_SUFFIX = "-pooler"
# The provisioning role's direct string for a store database, by store id (a secret).
AdminUrlFor = Callable[[str], Awaitable[str]]
# Like migrate_stores: the stores that serve traffic or are about to.
DEFAULT_STATUSES = (StoreStatus.ACTIVE, StoreStatus.PROVISIONING)


class Outcome(StrEnum):
    MOVED = "moved"
    WOULD_MOVE = "would move"
    WOULD_REPAIR = "would repair"
    # Already on its own role, or no database yet.
    SKIPPED = "skipped"


@dataclass(frozen=True)
class BackfillFailure:
    store_id: str
    reason: str


@dataclass(frozen=True)
class BackfillReport:
    moved: tuple[str, ...] = ()
    would_move: tuple[str, ...] = ()
    would_repair: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    failures: tuple[BackfillFailure, ...] = ()
    # True when the run stopped at the first failure with stores left untouched.
    stopped: bool = False

    @property
    def succeeded(self) -> bool:
        return not self.failures


def direct_endpoint(connection_string: str) -> str:
    """Neon's unpooled host for a pooled string (``ep-x-pooler.…`` → ``ep-x.…``)."""
    url = make_url(connection_string)
    host = url.host or ""
    first, dot, rest = host.partition(".")
    if not first.endswith(_POOLER_SUFFIX):
        return connection_string
    direct = f"{first.removesuffix(_POOLER_SUFFIX)}{dot}{rest}"
    return url.set(host=direct).render_as_string(hide_password=False)


async def provisioner_admin_url(store_id: str) -> str:
    return await get_database_provisioner(settings).admin_connection_string(store_id)


async def backfill_store_role(
    store_id: str,
    provider: SessionProvider,
    admin_connection: AdminConnection = open_admin_connection,
    *,
    dry_run: bool = False,
    admin_url_for: AdminUrlFor = provisioner_admin_url,
) -> Outcome:
    """Move one store onto its own role (or, with ``dry_run``, say whether it would)."""
    name = database_name_for(store_id)
    stored = await _stored_connection_string(store_id, provider)
    if stored is None:
        return Outcome.SKIPPED
    if make_url(stored).username == name:
        return await _repair(store_id, name, admin_connection, admin_url_for, dry_run)
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
            return Outcome.SKIPPED
        url = make_url(current)
        if url.username == name:
            return Outcome.SKIPPED  # moved by a concurrent run since the first read
        if url.database != name:
            raise StoreDatabaseUnavailable(store_id)
        if dry_run:
            return Outcome.WOULD_MOVE
        password = new_role_password()
        admin_url = direct_endpoint(current)
        async with admin_connection(admin_url) as connection:
            moved = await apply_store_role(connection, name, password)
        store_secrets.set_connection_string(store, with_role(current, name, password))
        await session.commit()
    async with admin_connection(admin_url) as connection:
        late = await move_owned_objects(connection, name)
    logger.info(
        "store moved to its own database role",
        extra={"store_id": store_id, "objects": moved + late},
    )
    return Outcome.MOVED


async def _stored_connection_string(
    store_id: str, provider: SessionProvider
) -> str | None:
    """The store's current string, read without a lock (to choose the path)."""
    async with provider.session() as session:
        store = (
            await session.execute(select(Store).where(Store.id == store_id))
        ).scalar_one_or_none()
        if store is None:
            raise StoreNotFound(store_id)
        return store_secrets.reveal_connection_string(store)


async def _repair(
    store_id: str,
    name: str,
    admin_connection: AdminConnection,
    admin_url_for: AdminUrlFor,
    dry_run: bool,
) -> Outcome:
    """A store already on its role: move what the shared role still owns there.

    The provisioning role's string comes from the provisioner (a Neon API call), so it is
    fetched here, with no platform row locked; the store's own string is not changed.
    """
    admin_url = await admin_url_for(store_id)
    async with admin_connection(admin_url) as connection:
        if dry_run:
            left = await count_leftover_owned(connection, name)
            return Outcome.WOULD_REPAIR if left else Outcome.SKIPPED
        late = await move_owned_objects(connection, name)
    if late:
        logger.info(
            "objects left on the shared role moved to the store role",
            extra={"store_id": store_id, "objects": late},
        )
    return Outcome.MOVED if late else Outcome.SKIPPED


async def select_store_ids(
    provider: SessionProvider, statuses: Sequence[StoreStatus] = DEFAULT_STATUSES
) -> list[str]:
    """Stores in ``statuses`` that have a connection string, in id order."""
    async with provider.session() as session:
        return list(
            (
                await session.execute(
                    select(Store.id)
                    .where(Store.connection_string_encrypted.is_not(None))
                    .where(Store.status.in_(statuses))
                    .order_by(Store.id)
                )
            ).scalars()
        )


async def backfill_store_roles(
    provider: SessionProvider | None = None,
    *,
    store_ids: Sequence[str] | None = None,
    statuses: Sequence[StoreStatus] = DEFAULT_STATUSES,
    dry_run: bool = False,
    continue_on_error: bool = False,
    admin_connection: AdminConnection = open_admin_connection,
    admin_url_for: AdminUrlFor = provisioner_admin_url,
) -> BackfillReport:
    """``store_ids``, or every store in ``statuses`` with a connection string.

    Stops at the first failure unless ``continue_on_error``.
    """
    provider = provider or DefaultSessionProvider(async_session_maker)
    if store_ids is None:
        store_ids = await select_store_ids(provider, statuses)
    found: dict[Outcome, list[str]] = {outcome: [] for outcome in Outcome}
    failures: list[BackfillFailure] = []
    stopped = False
    for index, store_id in enumerate(store_ids):
        try:
            outcome = await backfill_store_role(
                store_id,
                provider,
                admin_connection,
                dry_run=dry_run,
                admin_url_for=admin_url_for,
            )
        except Exception as exc:  # noqa: BLE001 - reported per store, never raised
            reason = (
                describe_failure(exc)
                if isinstance(exc, StoreRoleError)
                else safe_reason(exc)
            )
            logger.error(
                "store role backfill failed: %s", reason, extra={"store_id": store_id}
            )
            failures.append(BackfillFailure(store_id, reason))
            if not continue_on_error:
                stopped = index < len(store_ids) - 1
                break
            continue
        found[outcome].append(store_id)
    return BackfillReport(
        moved=tuple(found[Outcome.MOVED]),
        would_move=tuple(found[Outcome.WOULD_MOVE]),
        would_repair=tuple(found[Outcome.WOULD_REPAIR]),
        skipped=tuple(found[Outcome.SKIPPED]),
        failures=tuple(failures),
        stopped=stopped,
    )
