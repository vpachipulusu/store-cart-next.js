"""Tripwire for the API-to-store-database isolation check (KAN-195, AC 3).

Today only the migration runner opens a store database. The first product route that
calls ``open_store_session`` must come with isolation tests (a user of one organisation
cannot reach another organisation's store data through that route), so this test fails
when a new caller appears until the caller is added here on purpose, in the same change
as those tests in ``tests/api/test_tenant_isolation_*_e2e.py``.
"""

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
OPENERS = re.compile(r"\b(open_store_session|get_store_session)\b")
# Modules allowed to open a store database, with the isolation coverage that justifies it.
ALLOWED = {
    "services/store_sessions.py": "defines the opener",
    "services/store_migrations.py": "tenant isolation e2e: migration runner stays inside its database",
    "services/store_cart_purge.py": "tests/services/test_store_cart_purge_e2e.py: scheduled purge deletes expired carts in each store's own database only (KAN-252)",
    "api/store_db.py": "tests/api/test_products_e2e.py: every product route, two stores (KAN-245)",
    "api/v1/orders.py": "tests/api/test_checkout_hardening_e2e.py: cancel route, sibling and foreign store 404 (KAN-256)",
    "api/v1/order_refunds.py": "tests/api/test_order_refunds_e2e.py: refund route, foreign store and foreign order 404 (KAN-80)",
    "api/v1/webhooks_connect.py": "tests/api/test_checkout_hardening_e2e.py: expired event only touches the routed store (KAN-256)",
}


def test_only_known_modules_open_store_databases() -> None:
    callers = {
        path.relative_to(APP).as_posix()
        for path in APP.rglob("*.py")
        if OPENERS.search(path.read_text(encoding="utf-8"))
    }

    unexpected = callers - set(ALLOWED)

    assert not unexpected, (
        f"{sorted(unexpected)} open store databases: add API-level isolation tests "
        "for the new route(s) and list the module in ALLOWED"
    )


def test_every_allowed_module_still_exists() -> None:
    missing = [name for name in ALLOWED if not (APP / name).is_file()]

    assert not missing
