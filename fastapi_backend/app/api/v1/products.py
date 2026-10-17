"""Merchant product catalogue API (KAN-245): products, variants and image rows of one store.

Every route needs the internal service key, a verified session and a membership of the
organisation that owns ``{store_id}`` (``require_merchant``: unknown and foreign stores are
the same 404). The store database that is opened is the one of the store the membership
resolved, never an id taken from the body. Any member may read; changes need OWNER or ADMIN
and an ACTIVE store.

Errors are curated: 404 for unknown ids, 409 for a taken slug or SKU, 422 for invalid input.
No database error text reaches a client. Bodies reject unknown fields. Responses carry
``Cache-Control: no-store``. Money is integer minor units; ``currency`` is the platform
currency setting. There is no browser upload here: images are registered by ``storage_key``
after a presigned upload (``/v1/stores/{store_id}/uploads/images``).
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from app.api.auth import require_internal_key
from app.api.deps import SessionDep
from app.api.merchant import OWNER_ADMIN
from app.api.rate_limit import RATE_LIMIT_FAIL_CLOSED_RESPONSES, limit_by_subject
from app.api.store_db import store_products_service
from app.api.v1.auth import current_subject
from app.api.v1.organizations import no_store
from app.core.errors import ErrorResponse
from app.core.rate_limit import API_POLICY
from app.repositories.app_settings import AppSettingsRepository
from app.repositories.store_catalogue import ProductSummaryRow
from app.services.public_settings import PublicSettingsService
from app.services.store_product_types import (
    DEFAULT_PAGE_SIZE,
    MAX_CATEGORIES,
    MAX_ID_LENGTH,
    MAX_OFFSET,
    MAX_OPTIONS,
    MAX_PAGE_SIZE,
    MAX_VALUES_PER_OPTION,
    MAX_VARIANTS,
    UNSET,
    CatalogueConflict,
    CatalogueError,
    ImageNotFound,
    ImageRecord,
    InvalidProduct,
    NewOption,
    NewProduct,
    NewVariant,
    OptionRecord,
    ProductLimitReached,
    ProductNotFound,
    ProductPatch,
    ProductRecord,
    VariantNotFound,
    VariantPatch,
    VariantRecord,
)
from app.services.store_products import StoreProductsService

router = APIRouter(
    prefix="/v1/stores/{store_id}/products",
    tags=["products"],
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
        503: {"model": ErrorResponse},
    },
)

ReadService = Annotated[StoreProductsService, Depends(store_products_service())]
WriteService = Annotated[
    StoreProductsService, Depends(store_products_service(OWNER_ADMIN))
]
ProductId = Annotated[
    str, Path(min_length=1, max_length=MAX_ID_LENGTH, pattern=r"^[A-Za-z0-9_-]+$")
]
ChildId = ProductId


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OptionBody(Body):
    name: StrictStr
    values: Annotated[list[StrictStr], Field(max_length=MAX_VALUES_PER_OPTION)]


class VariantBody(Body):
    sku: StrictStr
    price_minor: StrictInt
    compare_at_price_minor: StrictInt | None = None
    weight_grams: StrictInt | None = None
    stock: StrictInt = 0
    options: Annotated[
        dict[StrictStr, StrictStr],
        Field(
            max_length=MAX_OPTIONS,
            description="Chosen value per option name; empty for a product without options.",
        ),
    ] = {}


class CreateProductRequest(Body):
    title: StrictStr
    slug: StrictStr | None = Field(
        default=None, description="Derived from the title when omitted."
    )
    description: StrictStr | None = None
    status: Literal["draft", "active"] = "draft"
    options: Annotated[list[OptionBody], Field(max_length=MAX_OPTIONS)] = []
    variants: Annotated[list[VariantBody], Field(min_length=1, max_length=MAX_VARIANTS)]
    category_ids: Annotated[list[StrictStr], Field(max_length=MAX_CATEGORIES)] = []


class UpdateProductRequest(Body):
    """Send only the fields to change; ``category_ids`` replaces the whole set."""

    title: StrictStr | None = None
    slug: StrictStr | None = None
    description: StrictStr | None = None
    status: Literal["draft", "active"] | None = None
    category_ids: (
        Annotated[list[StrictStr], Field(max_length=MAX_CATEGORIES)] | None
    ) = None


class UpdateVariantRequest(Body):
    """Send only the fields to change; null clears ``compare_at_price_minor`` and weight."""

    sku: StrictStr | None = None
    price_minor: StrictInt | None = None
    compare_at_price_minor: StrictInt | None = None
    weight_grams: StrictInt | None = None
    stock: StrictInt | None = None


class AddImageRequest(Body):
    storage_key: StrictStr = Field(
        description="The key from the presign response; must start with stores/{store_id}/."
    )
    alt_text: StrictStr | None = None


class OptionValueData(BaseModel):
    id: str
    value: str
    position: int


class OptionData(BaseModel):
    id: str
    name: str
    position: int
    values: list[OptionValueData]


class VariantChoiceData(BaseModel):
    option_id: str
    option_value_id: str


class VariantData(BaseModel):
    id: str
    sku: str
    price_minor: int
    compare_at_price_minor: int | None
    weight_grams: int | None
    stock: int
    position: int
    option_values: list[VariantChoiceData]


class ImageData(BaseModel):
    id: str
    storage_key: str
    alt_text: str | None
    position: int


class ProductData(BaseModel):
    id: str
    title: str
    slug: str
    description: str | None
    status: Literal["draft", "active"]
    currency: str
    created_at: datetime
    updated_at: datetime
    options: list[OptionData]
    variants: list[VariantData]
    category_ids: list[str]
    images: list[ImageData]


class ProductSummaryData(BaseModel):
    id: str
    title: str
    slug: str
    status: Literal["draft", "active"]
    created_at: datetime
    updated_at: datetime
    variant_count: int
    min_price_minor: int | None
    max_price_minor: int | None


class ProductResponse(BaseModel):
    data: ProductData


class ProductListResponse(BaseModel):
    data: list[ProductSummaryData]
    currency: str
    total: int
    limit: int
    offset: int


def _option_data(option: OptionRecord) -> OptionData:
    return OptionData(
        id=option.id,
        name=option.name,
        position=option.position,
        values=[OptionValueData(**vars(value)) for value in option.values],
    )


def _variant_data(variant: VariantRecord) -> VariantData:
    return VariantData(
        id=variant.id,
        sku=variant.sku,
        price_minor=variant.price_minor,
        compare_at_price_minor=variant.compare_at_price_minor,
        weight_grams=variant.weight_grams,
        stock=variant.stock,
        position=variant.position,
        option_values=[VariantChoiceData(**vars(c)) for c in variant.option_values],
    )


def _image_data(image: ImageRecord) -> ImageData:
    return ImageData(**vars(image))


def _status(value: str) -> Literal["draft", "active"]:
    return "active" if value == "active" else "draft"


def _product_response(product: ProductRecord, currency: str) -> ProductResponse:
    return ProductResponse(
        data=ProductData(
            id=product.id,
            title=product.title,
            slug=product.slug,
            description=product.description,
            status=_status(product.status),
            currency=currency,
            created_at=product.created_at,
            updated_at=product.updated_at,
            options=[_option_data(o) for o in product.options],
            variants=[_variant_data(v) for v in product.variants],
            category_ids=list(product.category_ids),
            images=[_image_data(i) for i in product.images],
        )
    )


def _summary_data(row: ProductSummaryRow) -> ProductSummaryData:
    return ProductSummaryData(
        id=row.id,
        title=row.title,
        slug=row.slug,
        status=_status(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        variant_count=row.variant_count,
        min_price_minor=row.min_price_minor,
        max_price_minor=row.max_price_minor,
    )


# Room for whitespace around a 100 character search; the service trims, then enforces 100.
MAX_SEARCH_QUERY_LENGTH = 200
NO_STORE = {"Cache-Control": "no-store"}


def http_error(error: CatalogueError) -> HTTPException:
    """Map a catalogue error to a response with a fixed message."""
    if isinstance(error, ProductNotFound):
        return HTTPException(404, "Product not found", headers=NO_STORE)
    if isinstance(error, VariantNotFound):
        return HTTPException(404, "Variant not found", headers=NO_STORE)
    if isinstance(error, ImageNotFound):
        return HTTPException(404, "Image not found", headers=NO_STORE)
    if isinstance(error, ProductLimitReached):
        # The message names the plan and says to upgrade; it holds no data of the store.
        return HTTPException(409, str(error), headers=NO_STORE)
    if isinstance(error, CatalogueConflict):
        return HTTPException(409, str(error), headers=NO_STORE)
    if isinstance(error, InvalidProduct):
        return HTTPException(422, str(error), headers=NO_STORE)
    return HTTPException(500, "Internal server error", headers=NO_STORE)


async def current_currency(session: SessionDep) -> str:
    return await PublicSettingsService(AppSettingsRepository(session)).currency()


CurrencyDep = Annotated[str, Depends(current_currency)]


def _new_variant(body: VariantBody) -> NewVariant:
    return NewVariant(
        sku=body.sku,
        price_minor=body.price_minor,
        compare_at_price_minor=body.compare_at_price_minor,
        weight_grams=body.weight_grams,
        stock=body.stock,
        options=body.options,
    )


def _sent(value: Any, name: str, sent: set[str]) -> Any:
    """``value`` when the client sent the field (even as null), else the UNSET marker."""
    return value if name in sent else UNSET


@router.get("", response_model=ProductListResponse, summary="List products")
async def list_products(
    response: Response,
    service: ReadService,
    currency: CurrencyDep,
    status: Literal["draft", "active"] | None = None,
    category_id: Annotated[str | None, Query(max_length=MAX_ID_LENGTH)] = None,
    q: Annotated[
        str | None,
        Query(
            max_length=MAX_SEARCH_QUERY_LENGTH,
            description="Title or SKU contains this text, ignoring case; trimmed, at most 100 characters.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET)] = 0,
) -> ProductListResponse:
    """Newest first, filtered by ``status``, ``category_id`` and ``q`` (all combine)."""
    no_store(response)
    try:
        page = await service.list_products(
            status=status,
            category_id=category_id,
            query=q,
            limit=limit,
            offset=offset,
        )
    except CatalogueError as error:
        raise http_error(error) from None
    return ProductListResponse(
        data=[_summary_data(row) for row in page.items],
        currency=currency,
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "",
    status_code=201,
    response_model=ProductResponse,
    summary="Create a product with its options and variants",
)
async def create_product(
    body: CreateProductRequest,
    response: Response,
    service: WriteService,
    currency: CurrencyDep,
) -> ProductResponse:
    no_store(response)
    try:
        product = await service.create(
            NewProduct(
                title=body.title,
                slug=body.slug,
                description=body.description,
                status=body.status,
                options=[NewOption(o.name, o.values) for o in body.options],
                variants=[_new_variant(v) for v in body.variants],
                category_ids=body.category_ids,
            )
        )
    except CatalogueError as error:
        raise http_error(error) from None
    return _product_response(product, currency)


@router.get("/{product_id}", response_model=ProductResponse, summary="Read a product")
async def read_product(
    product_id: ProductId,
    response: Response,
    service: ReadService,
    currency: CurrencyDep,
) -> ProductResponse:
    no_store(response)
    try:
        product = await service.get(product_id)
    except CatalogueError as error:
        raise http_error(error) from None
    return _product_response(product, currency)


@router.patch(
    "/{product_id}", response_model=ProductResponse, summary="Update a product"
)
async def update_product(
    product_id: ProductId,
    body: UpdateProductRequest,
    response: Response,
    service: WriteService,
    currency: CurrencyDep,
) -> ProductResponse:
    """Setting ``status`` to ``draft`` unpublishes; ``DELETE`` removes the product."""
    no_store(response)
    sent = body.model_fields_set
    try:
        product = await service.update(
            product_id,
            ProductPatch(
                title=_sent(body.title, "title", sent),
                slug=_sent(body.slug, "slug", sent),
                description=_sent(body.description, "description", sent),
                status=_sent(body.status, "status", sent),
                category_ids=_sent(body.category_ids, "category_ids", sent),
            ),
        )
    except CatalogueError as error:
        raise http_error(error) from None
    return _product_response(product, currency)


@router.delete("/{product_id}", status_code=204, summary="Delete a product")
async def delete_product(product_id: ProductId, service: WriteService) -> Response:
    """Removes the product, its variants, images and links. Orders keep their snapshots."""
    try:
        await service.delete(product_id)
    except CatalogueError as error:
        raise http_error(error) from None
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post(
    "/{product_id}/variants",
    status_code=201,
    response_model=ProductResponse,
    summary="Add a variant",
)
async def add_variant(
    product_id: ProductId,
    body: VariantBody,
    response: Response,
    service: WriteService,
    currency: CurrencyDep,
) -> ProductResponse:
    no_store(response)
    try:
        product = await service.add_variant(product_id, _new_variant(body))
    except CatalogueError as error:
        raise http_error(error) from None
    return _product_response(product, currency)


@router.patch(
    "/{product_id}/variants/{variant_id}",
    response_model=ProductResponse,
    summary="Update a variant",
)
async def update_variant(
    product_id: ProductId,
    variant_id: ChildId,
    body: UpdateVariantRequest,
    response: Response,
    service: WriteService,
    currency: CurrencyDep,
) -> ProductResponse:
    no_store(response)
    sent = body.model_fields_set
    try:
        product = await service.update_variant(
            product_id,
            variant_id,
            VariantPatch(
                sku=_sent(body.sku, "sku", sent),
                price_minor=_sent(body.price_minor, "price_minor", sent),
                compare_at_price_minor=_sent(
                    body.compare_at_price_minor, "compare_at_price_minor", sent
                ),
                weight_grams=_sent(body.weight_grams, "weight_grams", sent),
                stock=_sent(body.stock, "stock", sent),
            ),
        )
    except CatalogueError as error:
        raise http_error(error) from None
    return _product_response(product, currency)


@router.delete(
    "/{product_id}/variants/{variant_id}",
    response_model=ProductResponse,
    summary="Delete a variant",
)
async def delete_variant(
    product_id: ProductId,
    variant_id: ChildId,
    response: Response,
    service: WriteService,
    currency: CurrencyDep,
) -> ProductResponse:
    """The last variant of a product cannot be deleted. Orders keep their snapshots."""
    no_store(response)
    try:
        product = await service.delete_variant(product_id, variant_id)
    except CatalogueError as error:
        raise http_error(error) from None
    return _product_response(product, currency)


@router.post(
    "/{product_id}/images",
    status_code=201,
    response_model=ProductResponse,
    summary="Attach an uploaded image",
)
async def add_image(
    product_id: ProductId,
    body: AddImageRequest,
    response: Response,
    service: WriteService,
    currency: CurrencyDep,
) -> ProductResponse:
    """Records an image row for an object already uploaded to this store's prefix.

    422 when ``storage_key`` is not ``stores/{store_id}/{id}.(jpg|png|webp)`` of this store.
    The object's existence is not checked.
    """
    no_store(response)
    try:
        product = await service.add_image(product_id, body.storage_key, body.alt_text)
    except CatalogueError as error:
        raise http_error(error) from None
    return _product_response(product, currency)


@router.delete(
    "/{product_id}/images/{image_id}",
    response_model=ProductResponse,
    summary="Remove an image row",
)
async def delete_image(
    product_id: ProductId,
    image_id: ChildId,
    response: Response,
    service: WriteService,
    currency: CurrencyDep,
) -> ProductResponse:
    """Removes the row only; the stored object is not deleted."""
    no_store(response)
    try:
        product = await service.delete_image(product_id, image_id)
    except CatalogueError as error:
        raise http_error(error) from None
    return _product_response(product, currency)
