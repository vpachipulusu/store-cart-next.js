"""Order email templates (KAN-81). Pure functions: no I/O, no FastAPI imports.

Three kinds: the shopper's order confirmation and shipped notice, and the merchant's new-order
alert. Each kind has a platform default here; a store may override the subject and the plain
text body (a ``store_email_templates`` row, edited by KAN-117). Templates are stdlib
``string.Template`` with a fixed variable list per kind (``VARIABLES``). An override with an
unknown placeholder or bad syntax is logged (kind and store id only) and the default is used.

Safety:

* The subject loses every control and line-separator character and is capped, so no value or
  template can add a header line.
* HTML is only ever built here: the rendered text (template and values alike) goes through
  ``html.escape``, blank-line separated paragraphs become ``<p>``, the layout is fixed. A store
  cannot put markup or links in an email.
* The one link (the alert's dashboard order page on ``APP_PUBLIC_URL``) is built by code and
  escaped as an attribute; without ``APP_PUBLIC_URL`` there is none.
"""

import html
import logging
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from string import Template
from types import MappingProxyType
from urllib.parse import quote

logger = logging.getLogger("storecart.order_emails")

MAX_SUBJECT_LENGTH = 200
MAX_STORE_NAME_LENGTH = 100
NO_CARRIER = "Not provided"
# ISO 4217 minor unit digits that are not 2 (Stripe's zero-decimal and three-decimal lists).
ZERO_DECIMAL = frozenset(
    {
        "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG",
        "RWF", "UGX", "UYI", "VND", "VUV", "XAF", "XOF", "XPF",
    }
)  # fmt: skip
THREE_DECIMAL = frozenset({"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"})
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n+")
_LAYOUT = (
    '<!doctype html><html><body style="margin:0;padding:24px;'
    'font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;color:#111">'
    "{body}</body></html>"
)
_PARAGRAPH = '<p style="margin:0 0 16px">{}</p>'


class OrderEmailKind(StrEnum):
    ORDER_CONFIRMATION = "order_confirmation"
    ORDER_SHIPPED = "order_shipped"
    NEW_ORDER_ALERT = "new_order_alert"


VARIABLES: Mapping[OrderEmailKind, frozenset[str]] = MappingProxyType(
    {
        OrderEmailKind.ORDER_CONFIRMATION: frozenset(
            {"store_name", "order_id", "order_total", "items"}
        ),
        OrderEmailKind.ORDER_SHIPPED: frozenset(
            {"store_name", "order_id", "items", "tracking_number", "carrier"}
        ),
        OrderEmailKind.NEW_ORDER_ALERT: frozenset(
            {"store_name", "order_id", "order_total", "items", "order_url"}
        ),
    }
)


@dataclass(frozen=True)
class TemplateText:
    subject: str
    body_text: str


DEFAULT_TEMPLATES: Mapping[OrderEmailKind, TemplateText] = MappingProxyType(
    {
        OrderEmailKind.ORDER_CONFIRMATION: TemplateText(
            "Your order from $store_name",
            "Thank you for your order from $store_name.\n\n"
            "Order: $order_id\n\n$items\n\nTotal: $order_total\n\n"
            "We will email you again when it ships.",
        ),
        OrderEmailKind.ORDER_SHIPPED: TemplateText(
            "Your order from $store_name has shipped",
            "Good news: your order $order_id from $store_name is on its way.\n\n"
            "Tracking number: $tracking_number\nCarrier: $carrier\n\n$items",
        ),
        OrderEmailKind.NEW_ORDER_ALERT: TemplateText(
            "New order for $store_name",
            "$store_name has a new paid order.\n\n"
            "Order: $order_id\n\n$items\n\nTotal: $order_total",
        ),
    }
)


@dataclass(frozen=True)
class OrderLine:
    name: str
    variant_label: str | None
    quantity: int
    unit_price_minor: int


@dataclass(frozen=True)
class OrderFacts:
    order_id: str
    currency: str
    total_minor: int
    lines: tuple[OrderLine, ...]
    tracking_number: str | None
    carrier: str | None


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


def format_money(minor: int, currency: str) -> str:
    """``GBP 25.50`` from integer minor units, with the currency's own decimals."""
    code = currency.upper()
    digits = 0 if code in ZERO_DECIMAL else 3 if code in THREE_DECIMAL else 2
    whole, fraction = divmod(minor, 10**digits)
    amount = f"{whole:,}" if digits == 0 else f"{whole:,}.{fraction:0{digits}d}"
    return f"{code} {amount}"


def order_url(app_url: str | None, order_id: str) -> str | None:
    """The dashboard page of an order, or None when ``APP_PUBLIC_URL`` is not set."""
    if not app_url:
        return None
    return f"{app_url.rstrip('/')}/dashboard/orders/{quote(order_id, safe='')}"


def _single_line(value: str) -> str:
    """Control and separator characters removed (Unicode categories C, Zl and Zp)."""
    return "".join(
        ch
        for ch in value
        if not unicodedata.category(ch).startswith("C")
        and unicodedata.category(ch) not in ("Zl", "Zp")
    )


def _clean_subject(value: str) -> str:
    return " ".join(_single_line(value).split())[:MAX_SUBJECT_LENGTH]


def _line_text(line: OrderLine, currency: str) -> str:
    label = f" ({line.variant_label})" if line.variant_label else ""
    amount = format_money(line.unit_price_minor * line.quantity, currency)
    return f"{line.quantity} x {line.name}{label} - {amount}"


def template_values(
    kind: OrderEmailKind, store_name: str, facts: OrderFacts, link: str | None
) -> dict[str, str]:
    """Every variable of ``kind``, as text."""
    values = {
        "store_name": _single_line(store_name).strip()[:MAX_STORE_NAME_LENGTH],
        "order_id": facts.order_id,
        "order_total": format_money(facts.total_minor, facts.currency),
        "items": "\n".join(_line_text(line, facts.currency) for line in facts.lines),
        "tracking_number": facts.tracking_number or "",
        "carrier": facts.carrier or NO_CARRIER,
        "order_url": link or "",
    }
    return {name: values[name] for name in VARIABLES[kind]}


def _substitute(
    kind: OrderEmailKind, template: TemplateText, values: Mapping[str, str]
) -> TemplateText | None:
    """The filled template, or None when it uses a name outside ``VARIABLES`` or is malformed."""
    allowed = VARIABLES[kind]
    filled: list[str] = []
    for text in (template.subject, template.body_text):
        parsed = Template(text.replace("\r\n", "\n"))
        if not parsed.is_valid() or not set(parsed.get_identifiers()) <= allowed:
            return None
        # Valid and every name known: ``values`` holds them all, so this cannot raise.
        filled.append(parsed.substitute(values))
    return TemplateText(filled[0], filled[1])


def _html(text: str, link: str | None) -> str:
    paragraphs = [
        _PARAGRAPH.format(
            html.escape(part.strip("\n"), quote=True).replace("\n", "<br>")
        )
        for part in _PARAGRAPH_BREAK.split(text.strip())
        if part.strip()
    ]
    if link:
        anchor = f'<a href="{html.escape(link, quote=True)}">View the order</a>'
        paragraphs.append(_PARAGRAPH.format(anchor))
    return _LAYOUT.format(body="".join(paragraphs))


def render_order_email(
    kind: OrderEmailKind,
    *,
    store_id: str,
    store_name: str,
    facts: OrderFacts,
    override: TemplateText | None,
    link: str | None,
) -> RenderedEmail:
    """Subject, text and HTML of one email; the store's override when it is usable."""
    link = link if kind is OrderEmailKind.NEW_ORDER_ALERT else None
    values = template_values(kind, store_name, facts, link)
    default = _substitute(kind, DEFAULT_TEMPLATES[kind], values)
    assert default is not None  # the defaults use their own variables only
    filled = default
    if override is not None:
        custom = _substitute(kind, override, values)
        if custom is None:
            logger.warning(
                "store email template unusable: default used",
                extra={"store_id": store_id, "kind": kind.value},
            )
        else:
            filled = custom
    subject = _clean_subject(filled.subject) or _clean_subject(default.subject)
    text = filled.body_text.strip()
    if link:
        text = f"{text}\n\nView the order: {link}"
    return RenderedEmail(subject=subject, text=text, html=_html(filled.body_text, link))
