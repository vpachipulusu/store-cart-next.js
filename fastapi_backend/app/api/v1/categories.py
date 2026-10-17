"""Merchant category list for the product screens (KAN-246).

Read-only: any member of the organisation that owns ``{store_id}`` may list the categories
of that store, resolved exactly like the product routes (``require_merchant``, then the
store database of the id read back from the platform row). Categories are created and
edited elsewhere (KAN-71 schema); this route only feeds pickers and filters.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from app.api.auth import require_internal_key
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.store_db import store_products_service
from app.api.v1.auth import current_subject
from app.api.v1.organizations import no_store
from app.core.errors import ErrorResponse
from app.core.rate_limit import API_POLICY
from app.services.store_products import StoreProductsService

router = APIRouter(
    prefix="/v1/stores/{store_id}/categories",
    tags=["categories"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_subject(API_POLICY, current_subject)),
    ],
    responses={
        **RATE_LIMIT_FAIL_CLOSED_RESPONSES,
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)

ReadService = Annotated[StoreProductsService, Depends(store_products_service())]


class CategoryData(BaseModel):
    id: str
    name: str
    slug: str
    parent_id: str | None = Field(description="Null for a root category.")
    position: int = Field(description="Order among siblings, ascending.")


class CategoryListResponse(BaseModel):
    data: list[CategoryData]
    truncated: bool = Field(
        description="True when the store has more than 1000 categories."
    )


@router.get("", response_model=CategoryListResponse, summary="List categories")
async def list_categories(
    response: Response, service: ReadService
) -> CategoryListResponse:
    """Roots first, then by parent and position, at most 1000.

    ``truncated`` is true when the store holds more than that.
    """
    no_store(response)
    result = await service.list_categories()
    return CategoryListResponse(
        data=[
            CategoryData(
                id=row.id,
                name=row.name,
                slug=row.slug,
                parent_id=row.parent_id,
                position=row.position,
            )
            for row in result.items
        ],
        truncated=result.truncated,
    )
