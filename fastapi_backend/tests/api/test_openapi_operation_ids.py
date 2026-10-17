"""Operation ids as the TypeScript client sees them (tag prefix stripped, ADR-008).

A duplicate makes the generator rename one function (``cancelSubscription2``), so
callers can end up on the wrong route. Compare ``commands.generate_openapi_schema``.
"""

from collections import Counter
from typing import Any

from app.main import create_app
from commands.generate_openapi_schema import remove_operation_id_tag


def client_schema() -> dict[str, Any]:
    return remove_operation_id_tag(create_app().openapi())


def test_every_client_operation_id_is_unique():
    schema = client_schema()
    ids = [
        operation["operationId"]
        for path in schema["paths"].values()
        for operation in path.values()
    ]

    duplicated = [name for name, count in Counter(ids).items() if count > 1]

    assert duplicated == []


def test_existing_billing_cancel_keeps_its_operation_id():
    """The client's cancelSubscription must stay the organisation billing route."""
    cancel = client_schema()["paths"][
        "/v1/organizations/{organization_id}/billing/cancel"
    ]

    assert cancel["post"]["operationId"] == "cancel_subscription"


def test_admin_subscription_routes_use_their_own_operation_ids():
    schema = client_schema()
    admin_ids = {
        operation["operationId"]
        for path, methods in schema["paths"].items()
        if path.startswith("/v1/admin/subscriptions")
        for operation in methods.values()
    }

    assert admin_ids == {
        "admin_list_subscriptions",
        "admin_read_subscription",
        "admin_cancel_subscription",
        "admin_refund_payment",
        "admin_grant_subscription",
        "admin_revoke_grant",
    }


def test_admin_store_routes_use_their_own_operation_ids():
    schema = client_schema()
    admin_ids = {
        operation["operationId"]
        for path, methods in schema["paths"].items()
        if path.startswith(("/v1/admin/stores", "/v1/admin/organizations"))
        for operation in methods.values()
    }

    assert admin_ids == {
        "admin_list_organizations",
        "admin_list_stores",
        "admin_suspend_store",
        "admin_unsuspend_store",
        "admin_migrate_store",
        "admin_reprovision_store",
    }
