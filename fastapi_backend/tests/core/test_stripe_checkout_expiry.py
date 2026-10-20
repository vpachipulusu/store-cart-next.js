"""Session expiry on a connected account (KAN-256), against a mock transport.

``expires_at`` in the session form, and ``POST /v1/checkout/sessions/{id}/expire`` with the
``Stripe-Account`` header: success, a session that is no longer open (read back to tell expired
from complete) and the failures that must not be mistaken for a closed session.
"""

from dataclasses import replace
from typing import Any

import httpx
import pytest

from app.core.stripe_billing import StripeError, StripeRejected
from app.core.stripe_checkout import ExpireOutcome, HttpStripeCheckout, session_form
from tests.core.test_stripe_checkout import REQUEST, SECRET, client_for

ACCOUNT = "acct_merchant1"
SESSION = "cs_test_1"
EXPIRE_PATH = f"/v1/checkout/sessions/{SESSION}/expire"
READ_PATH = f"/v1/checkout/sessions/{SESSION}"


def answer(routes: dict[tuple[str, str], httpx.Response]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes[(request.method, request.url.path)]

    return handler


def test_the_session_form_carries_the_expiry_when_there_is_one() -> None:
    form = session_form(replace(REQUEST, expires_at=1_800_000_000))

    assert form["expires_at"] == "1800000000"


def test_the_session_form_leaves_out_the_expiry_when_there_is_none() -> None:
    assert "expires_at" not in session_form(REQUEST)


async def test_expiring_an_open_session_posts_to_the_connected_account() -> None:
    seen: list[httpx.Request] = []
    stripe = client_for(
        answer(
            {("POST", EXPIRE_PATH): httpx.Response(200, json={"status": "expired"})}
        ),
        seen,
    )

    outcome = await stripe.expire_session(ACCOUNT, SESSION)

    assert outcome is ExpireOutcome.EXPIRED
    assert [(r.method, r.url.path) for r in seen] == [("POST", EXPIRE_PATH)]
    assert seen[0].headers["Stripe-Account"] == ACCOUNT
    assert "Idempotency-Key" not in seen[0].headers


@pytest.mark.parametrize(
    ("status", "outcome"),
    [("expired", ExpireOutcome.EXPIRED), ("complete", ExpireOutcome.COMPLETE)],
)
async def test_a_session_that_is_not_open_is_read_back(
    status: str, outcome: ExpireOutcome
) -> None:
    seen: list[httpx.Request] = []
    stripe = client_for(
        answer(
            {
                ("POST", EXPIRE_PATH): httpx.Response(400, json={"error": {}}),
                ("GET", READ_PATH): httpx.Response(200, json={"status": status}),
            }
        ),
        seen,
    )

    result = await stripe.expire_session(ACCOUNT, SESSION)

    assert result is outcome
    assert seen[1].headers["Stripe-Account"] == ACCOUNT


async def test_a_refusal_for_a_session_that_is_still_open_is_an_error() -> None:
    stripe = client_for(
        answer(
            {
                ("POST", EXPIRE_PATH): httpx.Response(400, json={"error": {}}),
                ("GET", READ_PATH): httpx.Response(200, json={"status": "open"}),
            }
        ),
        [],
    )

    with pytest.raises(StripeRejected):
        await stripe.expire_session(ACCOUNT, SESSION)


async def test_a_session_stripe_does_not_know_cannot_be_paid() -> None:
    stripe = client_for(answer({("POST", EXPIRE_PATH): httpx.Response(404)}), [])

    assert await stripe.expire_session(ACCOUNT, SESSION) is ExpireOutcome.EXPIRED


@pytest.mark.parametrize("status_code", [500, 503, 401, 429])
async def test_other_failures_are_not_taken_for_a_closed_session(
    status_code: int,
) -> None:
    stripe = client_for(
        answer({("POST", EXPIRE_PATH): httpx.Response(status_code)}), []
    )

    with pytest.raises(StripeError):
        await stripe.expire_session(ACCOUNT, SESSION)


async def test_a_transport_failure_is_an_error() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    stripe = HttpStripeCheckout(
        SECRET, httpx.AsyncClient(transport=httpx.MockTransport(broken))
    )

    with pytest.raises(StripeError):
        await stripe.expire_session(ACCOUNT, SESSION)
