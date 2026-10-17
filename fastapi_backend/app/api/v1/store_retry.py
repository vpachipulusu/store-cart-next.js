"""Merchant retry of a FAILED store's provisioning (KAN-242).

``POST /v1/stores/{store_id}/retry-provisioning``: an OWNER or ADMIN of the store's
organisation re-runs the job that gave up. It is the admin re-run
(``AdminStoresService.reprovision``) with the merchant's identity in the audit row: the
same attempt cap (counted across both), the same single conditional UPDATE, the same
enqueue and compensation. Authorisation comes first (a store the caller cannot see is a
404, a STAFF member a 403); only then is the per-user and per-store limit spent, so a
caller who is turned away cannot burn a store's bucket. Error bodies carry fixed text:
no store data, no driver or QStash detail.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response

from app.api.auth import require_internal_key
from app.api.merchant import OWNER_ADMIN, require_merchant
from app.api.rate_limit import (
    RATE_LIMIT_FAIL_CLOSED_RESPONSES,
    RateLimiterDep,
    enforce_rate_limit,
    limit_by_subject,
)
from app.api.v1.admin_stores import (
    COMMIT_RETRY_AFTER,
    HANDLED,
    ServiceDep,
    StoreReprovisionData,
    StoreReprovisionResponse,
    http_error,
)
from app.api.v1.auth import current_subject
from app.core.errors import ErrorResponse
from app.core.permissions import AdminContext
from app.core.rate_limit import API_POLICY, RETRY_PROVISIONING_POLICY
from app.repositories.merchant import MerchantAccess
from app.services.admin_stores import (
    MAX_REPROVISION_ATTEMPTS,
    MERCHANT_RETRY,
    RETRY_LIMIT_MESSAGE,
)

router = APIRouter(
    prefix="/v1/stores/{store_id}",
    tags=["stores"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_subject(API_POLICY, current_subject)),
    ],
    responses={
        **RATE_LIMIT_FAIL_CLOSED_RESPONSES,
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)

_RETRY_RESPONSES: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorResponse,
        "description": "The store is not FAILED, or it was already retried the maximum "
        f"number of times ({MAX_REPROVISION_ATTEMPTS}, shared with admin re-runs): "
        f"`{RETRY_LIMIT_MESSAGE}`.",
    },
    502: {
        "model": ErrorResponse,
        "description": "The job could not be enqueued. The store goes back to FAILED "
        "and the attempt does not count against the cap, unless the job already "
        "moved it on, in which case it is left as it is.",
    },
    503: {
        "model": ErrorResponse,
        "description": "The change or its audit row could not be recorded and was "
        f"rolled back. Retry after `Retry-After` seconds ({COMMIT_RETRY_AFTER}). If "
        "it was the step that returns a failed enqueue to FAILED, the store may stay "
        "PROVISIONING and is logged for follow-up. Also returned when the rate "
        "limiter is unavailable.",
    },
}

RetryMerchant = Annotated[
    MerchantAccess,
    Depends(require_merchant(OWNER_ADMIN, any_status=True)),
]


async def limit_retry(
    request: Request,
    response: Response,
    limiter: RateLimiterDep,
    merchant: RetryMerchant,
) -> None:
    """Spend one hit of the user's bucket and one of the store's (after authorisation)."""
    scope = RETRY_PROVISIONING_POLICY.scope
    await enforce_rate_limit(
        request,
        response,
        limiter,
        RETRY_PROVISIONING_POLICY,
        [f"{scope}:user:{merchant.user_id}", f"{scope}:store:{merchant.store.id}"],
    )


@router.post(
    "/retry-provisioning",
    summary="Retry provisioning of a FAILED store (OWNER or ADMIN)",
    response_model=StoreReprovisionResponse,
    responses=_RETRY_RESPONSES,
    dependencies=[Depends(limit_retry)],
)
async def retry_store_provisioning(
    response: Response, merchant: RetryMerchant, service: ServiceDep
) -> StoreReprovisionResponse:
    response.headers["Cache-Control"] = "no-store"
    actor = AdminContext(merchant.user_id, merchant.role.value, frozenset())
    try:
        result = await service.reprovision(actor, merchant.store.id, MERCHANT_RETRY)
    except HANDLED as exc:
        raise http_error(exc) from None
    return StoreReprovisionResponse(
        data=StoreReprovisionData(
            store_id=merchant.store.id,
            status=result.status,
            attempt=result.attempt,
            max_attempts=MAX_REPROVISION_ATTEMPTS,
        )
    )
