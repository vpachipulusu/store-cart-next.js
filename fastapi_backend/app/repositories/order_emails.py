"""Order emails in one store database (KAN-81): the outbox, the templates and the order facts.

Takes the ``AsyncSession`` of one store (from the store session factory) and never commits:
the caller owns the transaction. There is no ORM model for store tables, so the SQL is
explicit and every value is a bound parameter. No business rules: which kinds to write and
when is decided in ``app/services/order_email_job.py``.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id


@dataclass(frozen=True)
class OrderEmailOrderRow:
    id: str
    currency: str
    total_minor: int
    customer_email: str | None
    tracking_number: str | None
    carrier: str | None


@dataclass(frozen=True)
class OrderEmailLineRow:
    product_name: str
    variant_label: str | None
    quantity: int
    unit_price_minor: int


@dataclass(frozen=True)
class TemplateRow:
    subject: str
    body_text: str


_INSERT_SQL = text(
    "INSERT INTO order_emails (id, order_id, kind) VALUES (:id, :order_id, :kind) "
    "ON CONFLICT (order_id, kind) DO NOTHING RETURNING kind"
)
_SET_CUSTOMER_EMAIL_SQL = text(
    "UPDATE orders SET customer_email = :email WHERE id = :id"
)
_PENDING_SQL = text(
    "SELECT kind FROM order_emails WHERE order_id = :order_id AND status = 'pending'"
    " AND kind = ANY(CAST(:kinds AS varchar[])) ORDER BY kind"
)
_IS_PENDING_SQL = text(
    "SELECT 1 FROM order_emails WHERE order_id = :order_id AND kind = :kind"
    " AND status = 'pending'"
)
_ORDER_SQL = text(
    "SELECT id, currency, total_minor, customer_email, tracking_number, carrier"
    " FROM orders WHERE id = :id"
)
_LINES_SQL = text(
    "SELECT product_name, variant_label, quantity, unit_price_minor"
    " FROM order_items WHERE order_id = :id ORDER BY id"
)
_TEMPLATE_SQL = text(
    "SELECT subject, body_text FROM store_email_templates WHERE kind = :kind"
)
# Every status change is conditional on ``pending``, so a row settles exactly once.
_FINISH_SQL = text(
    "UPDATE order_emails SET status = CAST(:status AS varchar), updated_at = now(),"
    " sent_at = CASE WHEN CAST(:status AS varchar) = 'sent' THEN now() END "
    "WHERE order_id = :order_id AND kind = :kind AND status = 'pending' RETURNING id"
)
_STATUS_SQL = text(
    "SELECT status FROM order_emails WHERE order_id = :order_id AND kind = :kind"
)
_ATTEMPT_SQL = text(
    "UPDATE order_emails SET attempts = attempts + 1, updated_at = now() "
    "WHERE order_id = :order_id AND kind = :kind AND status = 'pending'"
)


class OrderEmailsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, order_id: str, kinds: Sequence[str]) -> list[str]:
        """Add a ``pending`` row per kind; the kinds that were new (an existing row stays)."""
        inserted: list[str] = []
        for kind in kinds:
            row = (
                await self._session.execute(
                    _INSERT_SQL, {"id": new_id(), "order_id": order_id, "kind": kind}
                )
            ).first()
            if row is not None:
                inserted.append(row[0])
        return inserted

    async def set_customer_email(self, order_id: str, email: str) -> None:
        await self._session.execute(
            _SET_CUSTOMER_EMAIL_SQL, {"id": order_id, "email": email}
        )

    async def pending_kinds(self, order_id: str, kinds: Sequence[str]) -> list[str]:
        result = await self._session.execute(
            _PENDING_SQL, {"order_id": order_id, "kinds": list(kinds)}
        )
        return [row[0] for row in result]

    async def is_pending(self, order_id: str, kind: str) -> bool:
        result = await self._session.execute(
            _IS_PENDING_SQL, {"order_id": order_id, "kind": kind}
        )
        return result.first() is not None

    async def order(self, order_id: str) -> OrderEmailOrderRow | None:
        row = (
            (await self._session.execute(_ORDER_SQL, {"id": order_id}))
            .mappings()
            .first()
        )
        return OrderEmailOrderRow(**dict(row)) if row is not None else None

    async def lines(self, order_id: str) -> list[OrderEmailLineRow]:
        rows = (
            (await self._session.execute(_LINES_SQL, {"id": order_id})).mappings().all()
        )
        return [OrderEmailLineRow(**dict(row)) for row in rows]

    async def template(self, kind: str) -> TemplateRow | None:
        row = (
            (await self._session.execute(_TEMPLATE_SQL, {"kind": kind}))
            .mappings()
            .first()
        )
        return TemplateRow(**dict(row)) if row is not None else None

    async def finish(self, order_id: str, kind: str, status: str) -> bool:
        """``pending`` becomes ``status``; False when the row was not pending."""
        result = await self._session.execute(
            _FINISH_SQL, {"order_id": order_id, "kind": kind, "status": status}
        )
        return result.first() is not None

    async def status(self, order_id: str, kind: str) -> str | None:
        result = await self._session.execute(
            _STATUS_SQL, {"order_id": order_id, "kind": kind}
        )
        return result.scalar_one_or_none()

    async def count_attempt(self, order_id: str, kind: str) -> None:
        await self._session.execute(_ATTEMPT_SQL, {"order_id": order_id, "kind": kind})
