"""Public storefront catalogue (KAN-75): ``/v1/storefront/{slug}/products`` and ``/categories``.

Called only by the Next.js server (decision D14): the internal service key, no user session.
The slug must be an ACTIVE store, otherwise it is the same 404 as the storefront lookup. Only
published (``active``) products are visible, and a draft reads like an unknown product. The
bodies hold what a shop window shows and nothing else: no SKU, weight, exact stock, product
or category ids, or timestamps. Variant and option value ids are included because the cart
adds by variant id. Responses are ``no-store``: the Next.js server keeps its own per-store
cache and revalidates it when the merchant changes the catalogue.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel

from app.api.auth import require_internal_key
from app.api.rate_limit import RATE_LIMIT_RESPONSES, limit_by_client_ip
from app.api.store_db import NO_STORE_HEADERS, storefront_catalogue_service
from app.core.errors import ErrorResponse
from app.core.rate_limit import STOREFRONT_POLICY
from app.services.store_product_types import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    MAX_SLUG_LENGTH,
    CatalogueError,
)
from app.services.storefront_catalogue import (
    MAX_PUBLIC_OFFSET,
    PublicCategory,
    PublicImage,
    PublicProduct,
    StorefrontCatalogueService,
    StorefrontNotFound,
)

router = APIRouter(
    prefix="/v1/storefront/{slug}",
    tags=["storefront"],
    dependencies=[
        Depends(require_internal_key),
        Depends(limit_by_client_ip(STOREFRONT_POLICY)),
    ],
    responses={
        **RATE_LIMIT_RESPONSES,
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)

CatalogueService = Annotated[
    StorefrontCatalogueService, Depends(storefront_catalogue_service)
]
# Generous transport caps; the service applies the real rules so every error has one shape.
MAX_QUERY_PARAM_LENGTH = 400


class PublicImageData(BaseModel):
    url: str
    alt_text: str | None


class PublicProductSummaryData(BaseModel):
    title: str
    slug: str
    min_price_minor: int | None
    max_price_minor: int | None
    image: PublicImageData | None


class PublicProductListResponse(BaseModel):
    """Like the merchant ``ProductListResponse``: the page with its currency and totals."""

    data: list[PublicProductSummaryData]
    currency: str
    total: int
    limit: int
    offset: int


class PublicOptionValueData(BaseModel):
    id: str
    value: str


class PublicOptionData(BaseModel):
    name: str
    values: list[PublicOptionValueData]


class PublicVariantData(BaseModel):
    id: str
    price_minor: int
    compare_at_price_minor: int | None
    in_stock: bool
    option_value_ids: list[str]


class PublicCategoryData(BaseModel):
    name: str
    slug: str
    parent_slug: str | None


class PublicProductData(BaseModel):
    title: str
    slug: str
    description: str | None
    currency: str
    options: list[PublicOptionData]
    variants: list[PublicVariantData]
    images: list[PublicImageData]
    categories: list[PublicCategoryData]


class PublicProductResponse(BaseModel):
    success: Literal[True] = True
    data: PublicProductData


class PublicCategoryListResponse(BaseModel):
    success: Literal[True] = True
    data: list[PublicCategoryData]


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = NO_STORE_HEADERS["Cache-Control"]


def _http_error(error: CatalogueError) -> HTTPException:
    status = 404 if isinstance(error, StorefrontNotFound) else 422
    return HTTPException(status, str(error), headers=NO_STORE_HEADERS)


def _image(image: PublicImage) -> PublicImageData:
    return PublicImageData(url=image.url, alt_text=image.alt_text)


def _category(category: PublicCategory) -> PublicCategoryData:
    return PublicCategoryData(
        name=category.name, slug=category.slug, parent_slug=category.parent_slug
    )


def _product(product: PublicProduct) -> PublicProductData:
    return PublicProductData(
        title=product.title,
        slug=product.slug,
        description=product.description,
        currency=product.currency,
        options=[
            PublicOptionData(
                name=option.name,
                values=[
                    PublicOptionValueData(id=value.id, value=value.value)
                    for value in option.values
                ],
            )
            for option in product.options
        ],
        variants=[
            PublicVariantData(
                id=variant.id,
                price_minor=variant.price_minor,
                compare_at_price_minor=variant.compare_at_price_minor,
                in_stock=variant.in_stock,
                option_value_ids=list(variant.option_value_ids),
            )
            for variant in product.variants
        ],
        images=[_image(image) for image in product.images],
        categories=[_category(category) for category in product.categories],
    )


@router.get(
    "/products",
    response_model=PublicProductListResponse,
    summary="List published products",
    responses={422: {"model": ErrorResponse}},
)
async def list_storefront_products(
    response: Response,
    service: CatalogueService,
    category: Annotated[
        str | None,
        Query(max_length=MAX_SLUG_LENGTH, description="A category slug."),
    ] = None,
    q: Annotated[
        str | None,
        Query(
            max_length=MAX_QUERY_PARAM_LENGTH,
            description="Title contains this text, ignoring case; trimmed, at most 100 characters.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0, le=MAX_PUBLIC_OFFSET)] = 0,
) -> PublicProductListResponse:
    """Newest first; ``category`` and ``q`` combine. An unknown category is a 404."""
    _no_store(response)
    try:
        page = await service.list_products(
            category_slug=category, query=q, limit=limit, offset=offset
        )
    except CatalogueError as error:
        raise _http_error(error) from None
    return PublicProductListResponse(
        data=[
            PublicProductSummaryData(
                title=item.title,
                slug=item.slug,
                min_price_minor=item.min_price_minor,
                max_price_minor=item.max_price_minor,
                image=_image(item.image) if item.image is not None else None,
            )
            for item in page.items
        ],
        currency=page.currency,
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/products/{product_slug}",
    response_model=PublicProductResponse,
    summary="Read a published product",
)
async def read_storefront_product(
    product_slug: Annotated[str, Path(max_length=MAX_SLUG_LENGTH)],
    response: Response,
    service: CatalogueService,
) -> PublicProductResponse:
    """A published product with its options, variants, images and categories.

    A draft, an unknown slug and a malformed slug are the same 404 ``Product not found``.
    """
    _no_store(response)
    try:
        product = await service.get_product(product_slug)
    except CatalogueError as error:
        raise _http_error(error) from None
    return PublicProductResponse(data=_product(product))


@router.get(
    "/categories",
    response_model=PublicCategoryListResponse,
    summary="List categories",
)
async def list_storefront_categories(
    response: Response, service: CatalogueService
) -> PublicCategoryListResponse:
    """Roots first, then by parent and position."""
    _no_store(response)
    categories = await service.list_categories()
    return PublicCategoryListResponse(data=[_category(c) for c in categories])
