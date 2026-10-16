"""Image upload presigning for a store (KAN-66).

OWNER or ADMIN of an ACTIVE store only (``require_merchant`` treats POST as a write).
The response holds a presigned URL whose query string is a credential: it is never logged.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import require_internal_key
from app.api.deps import get_media_upload_service
from app.api.merchant import OWNER_ADMIN, require_merchant
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.v1.auth import current_subject
from app.api.v1.organizations import no_store
from app.core.errors import ErrorResponse
from app.core.rate_limit import API_POLICY
from app.repositories.merchant import MerchantAccess
from app.services.media_uploads import (
    MAX_IMAGE_BYTES,
    ImageContentType,
    InvalidUpload,
    MediaUploadService,
)

router = APIRouter(
    prefix="/v1/stores/{store_id}/uploads",
    tags=["media"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_subject(API_POLICY, current_subject)),
    ],
    responses={
        **RATE_LIMIT_FAIL_CLOSED_RESPONSES,
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse, "description": "Unsupported type or size"},
        503: {"model": ErrorResponse},
    },
)


class ImageUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: ImageContentType
    size_bytes: int = Field(gt=0, le=MAX_IMAGE_BYTES)


class ImageUploadData(BaseModel):
    upload_url: str
    method: Literal["PUT"]
    headers: dict[str, str]
    key: str
    public_url: str
    expires_at: datetime


class ImageUploadResponse(BaseModel):
    data: ImageUploadData


@router.post(
    "/images", response_model=ImageUploadResponse, summary="Presign an image upload"
)
async def presign_image_upload(
    body: ImageUploadRequest,
    response: Response,
    merchant: Annotated[MerchantAccess, Depends(require_merchant(OWNER_ADMIN))],
    service: Annotated[MediaUploadService, Depends(get_media_upload_service)],
) -> ImageUploadResponse:
    """Presign a PUT of one image under ``stores/{store_id}/``; the file never touches the API.

    Valid for 300 seconds. Send ``headers`` verbatim and a body of exactly ``size_bytes``.
    """
    no_store(response)
    try:
        upload = service.presign_image(
            merchant.store.id, body.content_type, body.size_bytes
        )
    except InvalidUpload as exc:
        raise HTTPException(422, str(exc)) from None
    return ImageUploadResponse(
        data=ImageUploadData(
            upload_url=upload.upload_url,
            method=upload.method,
            headers=upload.headers,
            key=upload.key,
            public_url=upload.public_url,
            expires_at=upload.expires_at,
        )
    )
