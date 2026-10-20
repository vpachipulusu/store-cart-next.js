"""The Idempotency-Key fingerprint of a refund request (KAN-80): shape and restock, order-free."""

from app.services.store_refunds import RefundLineInput, request_fingerprint

A = RefundLineInput("item_a", 1)
B = RefundLineInput("item_b", 2)


def test_the_order_of_lines_does_not_matter():
    assert request_fingerprint([A, B], False) == request_fingerprint([B, A], False)


def test_anything_else_changes_it():
    base = request_fingerprint([A], False)

    assert request_fingerprint([A], True) != base  # restock
    assert (
        request_fingerprint([RefundLineInput("item_a", 2)], False) != base
    )  # quantity
    assert request_fingerprint([A, B], False) != base  # more lines
    assert request_fingerprint(None, False) != base  # full vs lines


def test_a_full_refund_differs_from_an_empty_line_list():
    assert request_fingerprint(None, False) != request_fingerprint([], False)
