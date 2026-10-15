"""Public storefront lookup (KAN-65): ``GET /v1/storefront/{slug}``.

Called only by the Next.js server (decision D14), so it needs the internal service key,
but no user session. It is the one read across tenants, so it returns an explicit
allowlist of public fields for ACTIVE stores only. Every other case (unknown, malformed,
reserved, PROVISIONING, SUSPENDED, ARCHIVED) is the same 404 with the same headers.

Responses are cacheable: ``Cache-Control`` plus a content-hash ``ETag`` answered with
304 on ``If-None-Match``. Misses carry a short cache too, so unknown slugs stay cheap.
"""

import hashlib
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel

from app.api.auth import require_internal_key
from app.api.deps import SessionDep
from app.api.rate_limit import RATE_LIMIT_RESPONSES, limit_by_client_ip
from app.core.errors import ErrorResponse, error_response
from app.core.rate_limit import STOREFRONT_POLICY
from app.repositories.storefront import StorefrontRepository
from app.services.storefront import StorefrontService

SUCCESS_CACHE_CONTROL = "public, max-age=60, stale-while-revalidate=300"
MISS_CACHE_CONTROL = "public, max-age=30"
NOT_FOUND_MESSAGE = "Store not found"

router = APIRouter(
    prefix="/v1/storefront",
    tags=["storefront"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_client_ip(STOREFRONT_POLICY)),
    ],
    responses={
        **RATE_LIMIT_RESPONSES,
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)


class StorefrontData(BaseModel):
    """The public fields. Add a field here only when it is safe for anyone to read."""

    name: str
    slug: str


class StorefrontResponse(BaseModel):
    success: Literal[True] = True
    data: StorefrontData


def get_storefront_service(session: SessionDep) -> StorefrontService:
    return StorefrontService(StorefrontRepository(session))


ServiceDep = Annotated[StorefrontService, Depends(get_storefront_service)]


def _etag_for(body: bytes) -> str:
    return f'"{hashlib.sha256(body).hexdigest()[:32]}"'


def _matches(if_none_match: str | None, etag: str) -> bool:
    """RFC 9110 weak comparison of an ``If-None-Match`` list against ``etag``."""
    if if_none_match is None:
        return False
    candidates = [part.strip() for part in if_none_match.split(",")]
    return "*" in candidates or any(c.removeprefix("W/") == etag for c in candidates)


@router.get(
    "/{slug}",
    response_model=StorefrontResponse,
    responses={304: {"description": "Not modified (If-None-Match matched)"}},
)
async def read_storefront(
    slug: str,
    service: ServiceDep,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    """Public details of an ACTIVE store, by slug."""
    store = await service.lookup(slug)
    if store is None:
        return error_response(
            404, NOT_FOUND_MESSAGE, {"Cache-Control": MISS_CACHE_CONTROL}
        )
    content = StorefrontResponse(
        data=StorefrontData(name=store.name, slug=store.slug)
    ).model_dump_json()
    etag = _etag_for(content.encode())
    headers = {"Cache-Control": SUCCESS_CACHE_CONTROL, "ETag": etag}
    if _matches(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    return Response(content, media_type="application/json", headers=headers)
