"""Product CSV import for one store (KAN-74), beside the product routes of KAN-245.

``POST /v1/stores/{store_id}/products/import`` takes ``multipart/form-data`` with one
``file`` part. Authorisation is the product write path: internal key, verified session, an
OWNER or ADMIN membership of the organisation that owns ``{store_id}`` and an ACTIVE store
(``store_products_service(OWNER_ADMIN)``; unknown and foreign stores are the same 404). The
database opened is the one of the store the membership resolved.

The body is read here, after those dependencies, under a byte cap (413 above it), so an
unauthorised or oversized upload is never parsed. FastAPI would parse a declared ``File``
parameter before any dependency runs, which is why the multipart body is declared through
``openapi_extra`` instead and parsed from the capped bytes.

Rows are reported, not raised: a file that fails validation answers 200 with
``imported: 0`` and every problem by row and column, so the dashboard can show them all.
Nothing is written unless every row passes (``app.services.product_import``).
"""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile

from app.api.auth import require_internal_key
from app.api.merchant import OWNER_ADMIN
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.store_db import store_products_service
from app.api.v1.auth import current_subject
from app.api.v1.organizations import no_store
from app.core.errors import ErrorResponse
from app.core.rate_limit import API_POLICY, PRODUCT_IMPORT_POLICY
from app.services.product_import import (
    COLUMNS,
    MAX_IMPORT_BYTES,
    MAX_IMPORT_ROWS,
    TOO_LARGE_MESSAGE,
    ImportIssue,
    import_products,
)
from app.services.store_products import StoreProductsService

# Room for the multipart boundary and part headers around the file.
MAX_REQUEST_BYTES = MAX_IMPORT_BYTES + 16_384
NO_FILE_MESSAGE = "Attach the CSV file as the file field"
# A stalled upload must not hold the request (and the platform session) open.
READ_TIMEOUT_SECONDS = 30
TIMEOUT_MESSAGE = "The upload took too long"

router = APIRouter(
    prefix="/v1/stores/{store_id}/products",
    tags=["products"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_subject(API_POLICY, current_subject)),
    ],
    responses={
        **RATE_LIMIT_FAIL_CLOSED_RESPONSES,
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        408: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)

WriteService = Annotated[
    StoreProductsService, Depends(store_products_service(OWNER_ADMIN))
]

MULTIPART_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "title": "ImportProductsBody",
                    "required": ["file"],
                    "properties": {
                        "file": {
                            "type": "string",
                            "format": "binary",
                            "description": (
                                f"UTF-8 CSV, at most 1 MB ({MAX_IMPORT_BYTES} bytes) and "
                                f"{MAX_IMPORT_ROWS} rows. Columns: {', '.join(COLUMNS)}."
                            ),
                        }
                    },
                }
            }
        },
    }
}


class ImportIssueData(BaseModel):
    row: int | None = Field(
        description="Spreadsheet row (the header is row 1); null for the whole file."
    )
    column: str | None = Field(description="Column name; null for the whole row.")
    message: str


class ImportProductsResponse(BaseModel):
    imported: int = Field(description="Products created; 0 when any row failed.")
    product_ids: list[str]
    errors: list[ImportIssueData]
    truncated: bool = Field(description="More problems were found than are listed.")


def _issue(issue: ImportIssue) -> ImportIssueData:
    return ImportIssueData(row=issue.row, column=issue.column, message=issue.message)


async def _read_capped(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
        raise HTTPException(413, TOO_LARGE_MESSAGE)
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_REQUEST_BYTES:
            raise HTTPException(413, TOO_LARGE_MESSAGE)
        chunks.append(chunk)
    return b"".join(chunks)


async def _uploaded_file(request: Request) -> bytes:
    """The bytes of the ``file`` part; 400 for anything that is not one such part."""
    content_type = request.headers.get("content-type", "").lower()
    if not content_type.startswith("multipart/form-data"):
        raise HTTPException(400, NO_FILE_MESSAGE)
    try:
        async with asyncio.timeout(READ_TIMEOUT_SECONDS):
            body = await _read_capped(request)
    except TimeoutError:
        raise HTTPException(408, TIMEOUT_MESSAGE) from None

    async def replay() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    buffered = Request(request.scope, replay)
    async with buffered.form(max_files=1, max_fields=0) as form:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(400, NO_FILE_MESSAGE)
        content = await upload.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(413, TOO_LARGE_MESSAGE)
    return content


@router.post(
    "/import",
    response_model=ImportProductsResponse,
    summary="Import products from a CSV file",
    openapi_extra=MULTIPART_BODY,
    dependencies=[Depends(limit_by_subject(PRODUCT_IMPORT_POLICY, current_subject))],
)
async def import_products_csv(
    request: Request, response: Response, service: WriteService
) -> ImportProductsResponse:
    """All or nothing: 200 with ``imported`` and ids, or ``imported: 0`` and every problem."""
    no_store(response)
    content = await _uploaded_file(request)
    result = await import_products(service, content)
    return ImportProductsResponse(
        imported=result.imported,
        product_ids=list(result.product_ids),
        errors=[_issue(issue) for issue in result.errors],
        truncated=result.truncated,
    )
