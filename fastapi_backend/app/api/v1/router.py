from fastapi import APIRouter

from app.api.v1 import (
    admin_analytics,
    admin_audit_logs,
    admin_stores,
    admin_subscriptions,
    admin_users,
    auth,
    health,
    internal_provisioning,
    me,
    me_export,
    media,
    notifications,
    org_billing,
    organizations,
    products,
    settings,
    store_retry,
    storefront,
    stores,
    totp,
    webhooks,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(me.router)
api_router.include_router(me_export.router)
api_router.include_router(notifications.router)
api_router.include_router(totp.router)
api_router.include_router(webhooks.router)
api_router.include_router(internal_provisioning.router)
api_router.include_router(admin_users.router)
api_router.include_router(admin_audit_logs.router)
api_router.include_router(admin_stores.router)
api_router.include_router(admin_subscriptions.router)
api_router.include_router(admin_analytics.router)
api_router.include_router(org_billing.router)

api_router.include_router(organizations.router)
api_router.include_router(stores.router)
api_router.include_router(store_retry.router)
api_router.include_router(media.router)
api_router.include_router(products.router)
api_router.include_router(storefront.router)
api_router.include_router(settings.router)
