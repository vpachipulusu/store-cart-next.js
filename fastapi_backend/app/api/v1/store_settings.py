"""Merchant store settings API: shipping and tax of one store (KAN-82, KAN-83).

``GET`` for any member of the organisation that owns ``{store_id}``; ``PATCH`` needs OWNER
or ADMIN and an ACTIVE store (same resolution as the product routes: unknown and foreign
stores are the same 404). Money is integer minor units; the tax rate is in basis points
(2000 = 20%). ``PATCH`` changes only the fields sent; ``free_shipping_threshold_minor: null``
removes the threshold. Bodies reject unknown fields; responses carry ``Cache-Control: no-store``.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)

from app.api.auth import require_internal_key
from app.api.merchant import OWNER_ADMIN
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.store_db import store_settings_service
from app.api.v1.auth import current_subject
from app.api.v1.organizations import no_store
from app.core.errors import ErrorResponse
from app.core.rate_limit import API_POLICY
from app.repositories.store_settings import StoreSettingsRow
from app.services.store_settings import (
    MAX_AMOUNT_MINOR,
    MAX_TAX_RATE_BPS,
    InvalidStoreSettings,
    StoreSettingsService,
)

NO_STORE_HEADERS = {"Cache-Control": "no-store"}

router = APIRouter(
    prefix="/v1/stores/{store_id}/store-settings",
    tags=["store-settings"],
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

ReadService = Annotated[StoreSettingsService, Depends(store_settings_service())]
WriteService = Annotated[
    StoreSettingsService, Depends(store_settings_service(OWNER_ADMIN))
]


class StoreSettingsResponse(BaseModel):
    shipping_flat_rate_minor: int = Field(description="Charged per order, minor units.")
    free_shipping_threshold_minor: int | None = Field(
        description="Item subtotal that waives shipping; null = never free."
    )
    tax_rate_bps: int = Field(description="Tax rate in basis points (2000 = 20%).")
    prices_include_tax: bool = Field(
        description="True when catalogue prices already contain the tax."
    )
    updated_at: datetime


class UpdateStoreSettingsRequest(BaseModel):
    """Send only the fields to change. Only the threshold accepts null (it clears it)."""

    model_config = ConfigDict(extra="forbid")

    shipping_flat_rate_minor: StrictInt | None = Field(
        default=None,
        ge=0,
        le=MAX_AMOUNT_MINOR,
        description="Charged per order, minor units. Cannot be null.",
    )
    free_shipping_threshold_minor: StrictInt | None = Field(
        default=None,
        ge=1,
        le=MAX_AMOUNT_MINOR,
        description="Item subtotal that waives shipping. Null clears the threshold.",
    )
    tax_rate_bps: StrictInt | None = Field(
        default=None,
        ge=0,
        le=MAX_TAX_RATE_BPS,
        description="Tax rate in basis points (2000 = 20%). Cannot be null.",
    )
    prices_include_tax: StrictBool | None = Field(
        default=None,
        description="True when catalogue prices already contain the tax. Cannot be null.",
    )

    @model_validator(mode="after")
    def reject_null_on_required_fields(self) -> "UpdateStoreSettingsRequest":
        for name in self.model_fields_set - {"free_shipping_threshold_minor"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


def _response(row: StoreSettingsRow) -> StoreSettingsResponse:
    return StoreSettingsResponse(
        shipping_flat_rate_minor=row.shipping_flat_rate_minor,
        free_shipping_threshold_minor=row.free_shipping_threshold_minor,
        tax_rate_bps=row.tax_rate_bps,
        prices_include_tax=row.prices_include_tax,
        updated_at=row.updated_at,
    )


@router.get(
    "", response_model=StoreSettingsResponse, summary="Get shipping and tax settings"
)
async def get_store_settings(
    response: Response, service: ReadService
) -> StoreSettingsResponse:
    no_store(response)
    return _response(await service.get())


@router.patch(
    "",
    response_model=StoreSettingsResponse,
    summary="Update shipping and tax settings",
    description=(
        "Changes only the fields sent. `free_shipping_threshold_minor: null` clears the "
        "threshold; null on any other field is a 422."
    ),
    responses={422: {"model": ErrorResponse}},
)
async def update_store_settings(
    body: UpdateStoreSettingsRequest, response: Response, service: WriteService
) -> StoreSettingsResponse:
    no_store(response)
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    try:
        row = await service.update(changes)
    except InvalidStoreSettings as error:
        raise HTTPException(422, str(error), headers=NO_STORE_HEADERS) from None
    return _response(row)
