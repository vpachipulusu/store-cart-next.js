"""Order email templates (KAN-81): platform defaults, store overrides, escaping and money."""

import logging

import pytest

from app.services.order_email_templates import (
    DEFAULT_TEMPLATES,
    MAX_SUBJECT_LENGTH,
    VARIABLES,
    OrderEmailKind,
    OrderFacts,
    OrderLine,
    TemplateText,
    format_money,
    order_url,
    render_order_email,
)

STORE_ID = "store1"
FACTS = OrderFacts(
    order_id="order1",
    currency="GBP",
    total_minor=2550,
    lines=(
        OrderLine("Mug", None, 2, 1000),
        OrderLine("Tee", "M / Blue", 1, 550),
    ),
    tracking_number="TRK123",
    carrier="Royal Mail",
)


def render(
    kind: OrderEmailKind,
    override: TemplateText | None = None,
    *,
    store_name: str = "North Shop",
    facts: OrderFacts = FACTS,
    url: str | None = None,
):
    return render_order_email(
        kind,
        store_id=STORE_ID,
        store_name=store_name,
        facts=facts,
        override=override,
        link=url,
    )


@pytest.mark.parametrize(
    ("minor", "currency", "expected"),
    [
        (2550, "GBP", "GBP 25.50"),
        (5, "USD", "USD 0.05"),
        (123456789, "EUR", "EUR 1,234,567.89"),
        (1500, "JPY", "JPY 1,500"),
        (1234, "BHD", "BHD 1.234"),
        (0, "GBP", "GBP 0.00"),
    ],
)
def test_money_uses_the_currency_decimals(
    minor: int, currency: str, expected: str
) -> None:
    assert format_money(minor, currency) == expected


def test_every_kind_has_a_default_using_only_its_variables() -> None:
    for kind in OrderEmailKind:
        default = DEFAULT_TEMPLATES[kind]
        rendered = render(kind)
        assert rendered.subject
        assert rendered.text
        assert "$" not in rendered.text  # every placeholder was filled
        assert set(VARIABLES[kind]) >= {"store_name", "order_id"}
        assert default.subject and default.body_text


def test_the_confirmation_lists_the_lines_and_the_total() -> None:
    rendered = render(OrderEmailKind.ORDER_CONFIRMATION)

    assert "North Shop" in rendered.subject
    assert "order1" in rendered.text
    assert "2 x Mug - GBP 20.00" in rendered.text
    assert "1 x Tee (M / Blue) - GBP 5.50" in rendered.text
    assert "GBP 25.50" in rendered.text


def test_the_shipped_notice_carries_the_tracking_details() -> None:
    rendered = render(OrderEmailKind.ORDER_SHIPPED)

    assert "TRK123" in rendered.text
    assert "Royal Mail" in rendered.text


def test_a_shipped_notice_without_a_carrier_says_so() -> None:
    facts = OrderFacts("order1", "GBP", 100, (), "TRK1", None)

    rendered = render(OrderEmailKind.ORDER_SHIPPED, facts=facts)

    assert "Not provided" in rendered.text


def test_a_store_override_wins() -> None:
    override = TemplateText(
        "Thanks from $store_name", "Hi!\n\nOrder $order_id: $order_total"
    )

    rendered = render(OrderEmailKind.ORDER_CONFIRMATION, override)

    assert rendered.subject == "Thanks from North Shop"
    assert rendered.text == "Hi!\n\nOrder order1: GBP 25.50"


@pytest.mark.parametrize(
    "override",
    [
        TemplateText("Hello $customer", "Body"),  # unknown placeholder
        TemplateText(
            "Hello", "Tracking $tracking_number"
        ),  # not a confirmation variable
        TemplateText("Hello", "Broken $"),  # bad syntax
        TemplateText("Hello", "Broken ${store_name"),
    ],
)
def test_a_bad_override_falls_back_to_the_default_and_logs_ids_only(
    override: TemplateText, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    rendered = render(OrderEmailKind.ORDER_CONFIRMATION, override)

    assert rendered == render(OrderEmailKind.ORDER_CONFIRMATION)
    [record] = [r for r in caplog.records if "template" in r.getMessage()]
    assert record.levelno == logging.WARNING
    assert record.store_id == STORE_ID
    assert record.kind == "order_confirmation"
    assert "Hello" not in record.getMessage()


def test_a_dollar_sign_can_be_escaped() -> None:
    rendered = render(
        OrderEmailKind.ORDER_CONFIRMATION, TemplateText("Save $$5", "Body")
    )

    assert rendered.subject == "Save $5"


def test_the_subject_loses_control_characters_and_is_capped() -> None:
    rendered = render(
        OrderEmailKind.ORDER_CONFIRMATION,
        TemplateText("$store_name", "Body"),
        store_name="Evil\r\nBcc: x@y.test " + "z" * 400,
    )

    assert "\r" not in rendered.subject and "\n" not in rendered.subject
    assert " " not in rendered.subject
    assert len(rendered.subject) <= MAX_SUBJECT_LENGTH


def test_a_subject_that_cleans_to_nothing_uses_the_default_subject() -> None:
    rendered = render(OrderEmailKind.ORDER_CONFIRMATION, TemplateText("\x07", "Body"))

    assert rendered.subject == render(OrderEmailKind.ORDER_CONFIRMATION).subject


def test_html_escapes_the_template_and_every_value() -> None:
    override = TemplateText(
        "Hi", "<b>$store_name</b>\n\n<script>alert(1)</script>\nline two"
    )

    rendered = render(
        OrderEmailKind.ORDER_CONFIRMATION,
        override,
        store_name='<img src=x onerror="alert(1)">',
    )

    assert "<script>" not in rendered.html
    assert "<img" not in rendered.html
    assert "&lt;b&gt;&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&lt;/b&gt;" in (
        rendered.html
    )
    assert "<p" in rendered.html and "<br>" in rendered.html
    assert rendered.html.count("<p") == 2


def test_the_alert_links_to_the_dashboard_order_page() -> None:
    url = order_url("https://app.example.com", "order1")

    rendered = render(OrderEmailKind.NEW_ORDER_ALERT, url=url)

    assert url == "https://app.example.com/dashboard/orders/order1"
    assert f'<a href="{url}">' in rendered.html
    assert url in rendered.text


def test_the_link_is_escaped_as_an_attribute() -> None:
    rendered = render(
        OrderEmailKind.NEW_ORDER_ALERT, url='https://app.example.com/"><x'
    )

    assert 'href="https://app.example.com/&quot;&gt;&lt;x"' in rendered.html


def test_the_alert_has_no_link_without_an_app_url() -> None:
    rendered = render(OrderEmailKind.NEW_ORDER_ALERT, url=None)

    assert order_url(None, "order1") is None
    assert "<a " not in rendered.html
    assert "http" not in rendered.text


def test_only_the_alert_gets_a_link() -> None:
    rendered = render(
        OrderEmailKind.ORDER_CONFIRMATION, url="https://app.example.com/x"
    )

    assert "<a " not in rendered.html


def test_line_breaks_in_merchant_text_collapse_to_single_spaces() -> None:
    facts = OrderFacts(
        "order1",
        "GBP",
        100,
        (OrderLine("Mug\r\nBcc: x@y.test", "Large\u2028Blue", 1, 100),),
        "TRK\n42",
        "Royal\r\n\r\nMail",
    )
    override = TemplateText("$tracking_number", "$items|$tracking_number|$carrier")

    rendered = render(OrderEmailKind.ORDER_SHIPPED, override, facts=facts)

    assert rendered.text == (
        "1 x Mug Bcc: x@y.test (Large Blue) - GBP 1.00|TRK 42|Royal Mail"
    )
    assert rendered.subject == "TRK 42"
    assert "<br>" not in rendered.html


def test_every_platform_currency_formats_with_its_decimals() -> None:
    from app.services.public_settings import SUPPORTED_CURRENCIES

    formatted = {code: format_money(12345, code) for code in SUPPORTED_CURRENCIES}

    assert formatted["JPY"] == "JPY 12,345"
    assert all(
        value == f"{code} 123.45" for code, value in formatted.items() if code != "JPY"
    )
