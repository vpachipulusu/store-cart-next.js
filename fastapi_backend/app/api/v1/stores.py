"""Store routes by store id (KAN-59), authorised by ``require_merchant`` (KAN-52).

A store the caller cannot see is a 404 with the same body whether it exists or not.
Any member may read; changes need OWNER or ADMIN (a slug change needs OWNER) and an
ACTIVE store, because ``require_merchant`` treats every non-GET request as a write.
The service re-checks the role and status under a row lock before writing.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.api.auth import require_internal_key
from app.api.merchant import OWNER_ADMIN, require_merchant
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.v1.auth import current_subject
from app.api.v1.organizations import (
    HANDLED,
    ServiceDep,
    StoreResponse,
    UpdateRequest,
    http_error,
    no_store,
    request_id_of,
    store_data,
)
from app.core.errors import ErrorResponse
from app.core.rate_limit import API_POLICY
from app.repositories.merchant import MerchantAccess

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
        409: {"model": ErrorResponse},
    },
)


@router.get("", response_model=StoreResponse)
async def read_store(
    response: Response,
    merchant: Annotated[MerchantAccess, Depends(require_merchant())],
    service: ServiceDep,
) -> StoreResponse:
    no_store(response)
    try:
        store = await service.get_store(merchant.store.id)
    except HANDLED as exc:
        raise http_error(exc) from None
    return StoreResponse(data=store_data(store))


@router.patch("", response_model=StoreResponse)
async def update_store(
    body: UpdateRequest,
    request: Request,
    response: Response,
    merchant: Annotated[MerchantAccess, Depends(require_merchant(OWNER_ADMIN))],
    service: ServiceDep,
) -> StoreResponse:
    """Rename (OWNER or ADMIN) or change the slug (OWNER only) of an ACTIVE store."""
    no_store(response)
    try:
        store = await service.update_store(
            merchant, name=body.name, slug=body.slug, request_id=request_id_of(request)
        )
    except HANDLED as exc:
        raise http_error(exc) from None
    return StoreResponse(data=store_data(store))
