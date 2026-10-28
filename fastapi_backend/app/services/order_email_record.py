"""Order email rows in the store transaction that changed the order (KAN-81). No FastAPI imports.

The outbox rows (``order_emails``) are inserted ``ON CONFLICT DO NOTHING`` in the store
transaction that paid or fulfilled the order, together with the shopper's address, inside a
SAVEPOINT, so an email problem never costs the order change around it:

* SQLSTATE 42P01/42703 (the store database has not reached revision 0012 yet): skipped and
  logged; outside local and test also a Sentry event, since a wrong column name would
  otherwise switch every email off without a sound.
* A transient error is raised as ``OrderEmailFailed``: the order change rolls back and is
  retried (Stripe redelivers). Transient means serialization failure, deadlock, lock or
  statement timeout, the SQLSTATE classes 08 (connection), 53 (resources) and 57P (operator
  intervention), and any error without a SQLSTATE (a dropped connection, an interface error).
* Any other, deterministic SQLSTATE (42501, 23xxx, ...) is reported and skipped: a payment
  that is not recorded is worse than an email that is not sent.

A raw SQLAlchemy error never leaves this module: its text carries the statement parameters,
which include the shopper's address. Only the class name and SQLSTATE are logged or reported.
"""

import logging
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.sentry import report_exception
from app.repositories.order_emails import OrderEmailsRepository
from app.services.order_email_job import OrderEmailFailed, OrderEmailJob
from app.services.order_email_templates import OrderEmailKind
from app.services.store_migrations import safe_reason

logger = logging.getLogger("storecart.order_emails")

MAX_CUSTOMER_EMAIL_LENGTH = 254
MISSING_SCHEMA = frozenset({"42P01", "42703"})  # undefined_table, undefined_column
# serialization_failure, deadlock_detected, lock_not_available, query_canceled
TRANSIENT = frozenset({"40001", "40P01", "55P03", "57014"})
# connection_exception, insufficient_resources, operator_intervention (admin shutdown, ...)
TRANSIENT_PREFIXES = ("08", "53", "57P")


def clean_customer_email(value: object) -> str | None:
    """The shopper's address from Stripe, trimmed, or None when it cannot be stored.

    Mirrors ``ck_orders_customer_email`` (3 to 254 characters, the first ``@`` after the
    first character) and refuses whitespace and control characters, so the write can never
    fail its CHECK.
    """
    if not isinstance(value, str):
        return None
    email = value.strip()
    if not 3 <= len(email) <= MAX_CUSTOMER_EMAIL_LENGTH or email.find("@") < 1:
        return None
    if any(ch.isspace() or not ch.isprintable() for ch in email):
        return None
    return email


def _absorb_or_raise(exc: SQLAlchemyError, *, store_id: str, order_id: str) -> None:
    """Classify a failed email write or read (see the module docstring); never re-raises
    ``exc`` itself."""
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
    reason = safe_reason(exc)
    extra = {"store_id": store_id, "order_id": order_id}
    if (
        not isinstance(sqlstate, str)
        or sqlstate in TRANSIENT
        or sqlstate.startswith(TRANSIENT_PREFIXES)
    ):
        raise OrderEmailFailed(reason) from None
    if sqlstate in MISSING_SCHEMA:
        logger.warning("order email skipped: store schema: %s", reason, extra=extra)
        if not settings.relaxed_environment:
            report_exception(OrderEmailFailed(f"store schema: {reason}"))
        return
    # A warning, not an error: the report below is the one Sentry event.
    logger.warning("order email skipped: %s", reason, extra=extra)
    report_exception(OrderEmailFailed(reason))


async def record_order_emails(
    session: AsyncSession,
    *,
    store_id: str,
    order_id: str,
    kinds: Sequence[OrderEmailKind],
    customer_email: str | None = None,
) -> list[OrderEmailKind]:
    """Write the outbox rows (and the shopper's address) in a SAVEPOINT; the kinds added.

    Runs inside the caller's transaction, which it never commits.
    """
    try:
        async with session.begin_nested():
            repository = OrderEmailsRepository(session)
            if customer_email is not None:
                await repository.set_customer_email(order_id, customer_email)
            added = await repository.insert(order_id, [kind.value for kind in kinds])
    except SQLAlchemyError as exc:
        _absorb_or_raise(exc, store_id=store_id, order_id=order_id)
        return []
    return [OrderEmailKind(kind) for kind in added]


async def pending_jobs(
    session: AsyncSession,
    *,
    store_id: str,
    order_id: str,
    kinds: Sequence[OrderEmailKind],
) -> list[OrderEmailJob]:
    """The jobs of ``kinds`` still ``pending`` for the order (none on a pre-0012 store)."""
    try:
        async with session.begin_nested():
            found = await OrderEmailsRepository(session).pending_kinds(
                order_id, [kind.value for kind in kinds]
            )
    except SQLAlchemyError as exc:
        _absorb_or_raise(exc, store_id=store_id, order_id=order_id)
        return []
    return [OrderEmailJob(store_id, order_id, OrderEmailKind(kind)) for kind in found]
