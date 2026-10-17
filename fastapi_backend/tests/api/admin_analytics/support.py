"""Constants shared by the admin analytics e2e tests (KAN-119)."""

PRICE_IDS = {
    "STRIPE_PRICE_ID_PRO_MONTHLY": "price_pro_m",
    "STRIPE_PRICE_ID_PRO_YEARLY": "price_pro_y",
    "STRIPE_PRICE_ID_ENTERPRISE_MONTHLY": "price_ent_m",
    "STRIPE_PRICE_ID_ENTERPRISE_YEARLY": None,
}
BASE = "/v1/admin/analytics"
ROUTES = [
    ("GET", f"{BASE}/overview", "users.read"),
    ("GET", f"{BASE}/revenue", "subscriptions.read"),
    ("GET", f"{BASE}/system", "settings.read"),
    ("POST", f"{BASE}/subscription-sync", "subscriptions.sync"),
]
