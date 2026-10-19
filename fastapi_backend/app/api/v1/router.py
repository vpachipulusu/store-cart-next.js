from fastapi import APIRouter

from app.api.v1 import (
    admin_analytics,
    admin_audit_logs,
    admin_stores,
    admin_subscriptions,
    admin_users,
    auth,
    cart,
    categories,
    health,
    internal_provisioning,
    me,
    me_export,
    media,
    notifications,
    orders,
    org_billing,
    org_connect,
    organizations,
    product_import,
    products,
    settings,
    store_retry,
    store_settings,
    storefront,
    storefront_catalogue,
    stores,
    totp,
    webhooks,
    webhooks_connect,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(me.router)
api_router.include_router(me_export.router)
api_router.include_router(notifications.router)
api_router.include_router(totp.router)
api_router.include_router(webhooks.router)
api_router.include_router(webhooks_connect.router)
api_router.include_router(internal_provisioning.router)
api_router.include_router(admin_users.router)
api_router.include_router(admin_audit_logs.router)
api_router.include_router(admin_stores.router)
api_router.include_router(admin_subscriptions.router)
api_router.include_router(admin_analytics.router)
api_router.include_router(org_billing.router)
api_router.include_router(org_connect.router)

api_router.include_router(organizations.router)
api_router.include_router(stores.router)
api_router.include_router(store_retry.router)
api_router.include_router(media.router)
api_router.include_router(product_import.router)
api_router.include_router(products.router)
api_router.include_router(orders.router)
api_router.include_router(categories.router)
api_router.include_router(storefront.router)
api_router.include_router(storefront_catalogue.router)
api_router.include_router(cart.router)
api_router.include_router(settings.router)
api_router.include_router(store_settings.router)
