from fastapi import APIRouter

from app.api.v1 import admin_users, auth, health, me, org_billing, totp, webhooks

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(me.router)
api_router.include_router(totp.router)
api_router.include_router(webhooks.router)
api_router.include_router(admin_users.router)
api_router.include_router(org_billing.router)
