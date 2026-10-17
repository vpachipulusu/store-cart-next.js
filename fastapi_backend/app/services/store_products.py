"""Products, variants and images in one store database (KAN-245). No FastAPI imports.

The service works on the ``AsyncSession`` of one store, opened by the store session
factory (``store_sessions``, the only door to a store database), and owns the transaction:
every write function commits once, or rolls back and raises a curated error. Database
constraint violations are translated here into ``CatalogueConflict`` (409) or
``InvalidProduct`` (422) with fixed messages; raw driver errors never leave this module.

Rules kept here because the database cannot express them (``docs/developer/backend-store-catalogue.md``):

* a variant picks exactly one value of every option of its product, and no two variants of a
  product share a combination (the product row is locked while checking);
* a product always keeps at least one variant;
* ``compare_at`` equal to the price means "no sale" and is stored as null; below it is invalid;
* a create fails with ``ProductLimitReached`` when the store already holds the plan's
  maximum number of products (KAN-84); the count runs under an advisory lock in the same
  transaction as the insert, so two concurrent creates cannot both take the last slot;
* an image ``storage_key`` must live under this store's own prefix ``stores/{store_id}/``.
"""

from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy.exc import DataError, DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.core.plans import Plan
from app.repositories.store_catalogue import StoreCatalogueRepository
from app.services.plan_limits import product_limit_message
from app.services.store_product_rules import (
    CONFLICTS,
    CleanVariant,
    OptionLookup,
    clean_category_ids,
    clean_optional_text,
    clean_options,
    clean_slug,
    clean_status,
    clean_text,
    clean_variant,
    group_choices,
    image_key_for_store,
    image_record,
    is_retryable,
    option_lookup,
    option_records,
    slugify,
    translate_error,
    variant_changes,
    variant_records,
)
from app.services.store_product_types import (
    DEFAULT_PAGE_SIZE,
    MAX_ALT_TEXT_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_ID_LENGTH,
    MAX_IMAGES,
    MAX_OFFSET,
    MAX_PAGE_SIZE,
    MAX_TITLE_LENGTH,
    MAX_VARIANTS,
    CatalogueConflict,
    ImageNotFound,
    InvalidProduct,
    NewProduct,
    NewVariant,
    ProductLimitReached,
    ProductNotFound,
    ProductPage,
    ProductPatch,
    ProductRecord,
    Unset,
    VariantNotFound,
    VariantPatch,
)

PlanLookup = Callable[[], Awaitable[Plan]]


class StoreProductsService:
    def __init__(
        self,
        repository: StoreCatalogueRepository,
        session: AsyncSession,
        store_id: str,
        plan: PlanLookup,
    ) -> None:
        # Resolves the organisation's plan on create (required: no silent unlimited).
        self._plan = plan
        self._repository = repository
        self._session = session
        self._store_id = store_id

    # --- reads --------------------------------------------------------------------

    async def get(self, product_id: str) -> ProductRecord:
        product = await self._repository.get_product(product_id)
        if product is None:
            raise ProductNotFound
        options = await self._repository.list_options(product_id)
        values = await self._repository.list_option_values(product_id)
        variants = await self._repository.list_variants(product_id)
        choices = await self._repository.list_variant_choices(product_id)
        images = await self._repository.list_images(product_id)
        return ProductRecord(
            id=product.id,
            title=product.title,
            slug=product.slug,
            description=product.description,
            status=product.status,
            created_at=product.created_at,
            updated_at=product.updated_at,
            options=option_records(options, values),
            variants=variant_records(variants, choices),
            category_ids=tuple(await self._repository.list_category_ids(product_id)),
            images=tuple(image_record(image) for image in images),
        )

    async def list_products(
        self,
        *,
        status: str | None = None,
        category_id: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> ProductPage:
        if status is not None:
            status = clean_status(status)
        if not 1 <= limit <= MAX_PAGE_SIZE or not 0 <= offset <= MAX_OFFSET:
            raise InvalidProduct("Page size or offset is out of range")
        if category_id is not None and (
            not 1 <= len(category_id) <= MAX_ID_LENGTH or "\x00" in category_id
        ):
            raise InvalidProduct("Unknown category")
        total = await self._repository.count_products(
            status=status, category_id=category_id
        )
        items = await self._repository.list_products(
            status=status, category_id=category_id, limit=limit, offset=offset
        )
        return ProductPage(tuple(items), total, limit, offset)

    # --- products -----------------------------------------------------------------

    async def create(self, data: NewProduct) -> ProductRecord:
        title = clean_text(data.title, "Title", MAX_TITLE_LENGTH)
        slug = clean_slug(data.slug) if data.slug is not None else slugify(title)
        if not slug:
            raise InvalidProduct("Provide a slug: the title has no usable characters")
        description = clean_optional_text(
            data.description, "Description", MAX_DESCRIPTION_LENGTH
        )
        status = clean_status(data.status)
        options = clean_options(data.options)
        if not 1 <= len(data.variants) <= MAX_VARIANTS:
            raise InvalidProduct(f"A product has 1 to {MAX_VARIANTS} variants")
        if not options and len(data.variants) != 1:
            raise InvalidProduct("A product without options has exactly one variant")
        category_ids = await self._checked_categories(data.category_ids)
        product_id = new_id()
        plan = await self._plan()

        async def write() -> None:
            if plan.max_products is not None:
                # Counting relies on READ COMMITTED (the default): the count must see
                # rows the previous lock holder committed.
                await self._repository.lock_catalogue()
                if await self._repository.count_all_products() >= plan.max_products:
                    raise ProductLimitReached(product_limit_message(plan))
            await self._repository.insert_product(
                product_id=product_id,
                title=title,
                slug=slug,
                description=description,
                status=status,
            )
            lookup = await self._insert_options(product_id, options)
            await self._insert_variants(product_id, data.variants, lookup)
            await self._repository.replace_categories(product_id, category_ids)

        await self._commit(write)
        return await self.get(product_id)

    async def update(self, product_id: str, patch: ProductPatch) -> ProductRecord:
        changes: dict[str, object] = {}
        if not isinstance(patch.title, Unset):
            changes["title"] = clean_text(patch.title, "Title", MAX_TITLE_LENGTH)
        if not isinstance(patch.slug, Unset):
            changes["slug"] = clean_slug(patch.slug)
        if not isinstance(patch.description, Unset):
            changes["description"] = clean_optional_text(
                patch.description, "Description", MAX_DESCRIPTION_LENGTH
            )
        if not isinstance(patch.status, Unset):
            changes["status"] = clean_status(patch.status)
        categories: tuple[str, ...] | None = None
        if not isinstance(patch.category_ids, Unset):
            categories = await self._checked_categories(patch.category_ids)
        if not changes and categories is None:
            raise InvalidProduct("No changes given")

        async def write() -> None:
            await self._lock(product_id)
            await self._repository.update_product(product_id, changes)
            if categories is not None:
                await self._repository.replace_categories(product_id, categories)

        await self._commit(write)
        return await self.get(product_id)

    async def delete(self, product_id: str) -> None:
        """Delete the product with its variants, images and links.

        Orders keep their snapshots (their product and variant links become null).
        The image objects in R2 are not deleted here.
        """

        async def write() -> None:
            if not await self._repository.delete_product(product_id):
                raise ProductNotFound

        await self._commit(write)

    # --- variants -----------------------------------------------------------------

    async def add_variant(self, product_id: str, variant: NewVariant) -> ProductRecord:
        async def write() -> None:
            await self._lock(product_id)
            if await self._repository.count_variants(product_id) >= MAX_VARIANTS:
                raise InvalidProduct(f"A product has at most {MAX_VARIANTS} variants")
            options = await self._repository.list_options(product_id)
            if not options:
                raise InvalidProduct(
                    "A product without options has exactly one variant"
                )
            values = await self._repository.list_option_values(product_id)
            clean = clean_variant(variant, option_lookup(options, values))
            existing = group_choices(
                await self._repository.list_variant_choices(product_id)
            )
            taken = {
                frozenset((c.option_id, c.option_value_id) for c in group)
                for group in existing.values()
            }
            if clean.combination in taken:
                raise CatalogueConflict("A variant with these options already exists")
            await self._insert_variant(
                product_id,
                clean,
                await self._repository.next_variant_position(product_id),
            )

        await self._commit(write)
        return await self.get(product_id)

    async def update_variant(
        self, product_id: str, variant_id: str, patch: VariantPatch
    ) -> ProductRecord:
        async def write() -> None:
            await self._lock(product_id)
            current = await self._repository.get_variant(variant_id, product_id)
            if current is None:
                raise VariantNotFound
            changes = variant_changes(current, patch)
            if not changes:
                raise InvalidProduct("No changes given")
            await self._repository.update_variant(variant_id, product_id, changes)

        await self._commit(write)
        return await self.get(product_id)

    async def delete_variant(self, product_id: str, variant_id: str) -> ProductRecord:
        async def write() -> None:
            await self._lock(product_id)
            if await self._repository.get_variant(variant_id, product_id) is None:
                raise VariantNotFound
            if await self._repository.count_variants(product_id) <= 1:
                raise InvalidProduct("A product needs at least one variant")
            await self._repository.delete_variant(variant_id, product_id)

        await self._commit(write)
        return await self.get(product_id)

    # --- images -------------------------------------------------------------------

    async def add_image(
        self, product_id: str, storage_key: str, alt_text: str | None
    ) -> ProductRecord:
        key = image_key_for_store(self._store_id, storage_key)
        alt = clean_optional_text(alt_text, "Alt text", MAX_ALT_TEXT_LENGTH)

        async def write() -> None:
            await self._lock(product_id)
            if await self._repository.count_images(product_id) >= MAX_IMAGES:
                raise InvalidProduct(f"A product has at most {MAX_IMAGES} images")
            await self._repository.insert_image(
                image_id=new_id(),
                product_id=product_id,
                storage_key=key,
                alt_text=alt,
                position=await self._repository.next_image_position(product_id),
            )

        await self._commit(write)
        return await self.get(product_id)

    async def delete_image(self, product_id: str, image_id: str) -> ProductRecord:
        async def write() -> None:
            await self._lock(product_id)
            if not await self._repository.delete_image(image_id, product_id):
                raise ImageNotFound

        await self._commit(write)
        return await self.get(product_id)

    # --- internals ----------------------------------------------------------------

    async def _lock(self, product_id: str) -> None:
        if not await self._repository.lock_product(product_id):
            raise ProductNotFound

    async def _checked_categories(self, value: object) -> tuple[str, ...]:
        category_ids = clean_category_ids(value)
        if category_ids:
            known = await self._repository.existing_category_ids(category_ids)
            if known != set(category_ids):
                raise InvalidProduct("Unknown category")
        return category_ids

    async def _commit(self, write: Callable[[], Awaitable[None]]) -> None:
        """Run ``write`` and commit; roll back and raise a curated error on any failure.

        Deferred constraints (image positions, option links) fail at ``COMMIT``, so the
        commit sits inside the same translation.
        """
        try:
            await write()
            await self._session.commit()
        except (IntegrityError, DataError) as error:
            await self._session.rollback()
            translated = translate_error(error)
            if translated is None:
                raise
            raise translated from None
        except DBAPIError as error:
            await self._session.rollback()
            if is_retryable(error):
                raise CatalogueConflict("The store is busy, retry") from None
            raise
        except BaseException:
            await self._session.rollback()
            raise

    async def _insert_options(
        self, product_id: str, options: Sequence[tuple[str, list[str]]]
    ) -> dict[str, dict[str, tuple[str, str]]]:
        lookup: dict[str, dict[str, tuple[str, str]]] = {}
        for position, (name, values) in enumerate(options):
            option_id = new_id()
            await self._repository.insert_option(
                option_id=option_id,
                product_id=product_id,
                name=name,
                position=position,
            )
            by_value: dict[str, tuple[str, str]] = {}
            for value_position, value in enumerate(values):
                value_id = new_id()
                await self._repository.insert_option_value(
                    value_id=value_id,
                    option_id=option_id,
                    value=value,
                    position=value_position,
                )
                by_value[value.lower()] = (option_id, value_id)
            lookup[name.lower()] = by_value
        return lookup

    async def _insert_variants(
        self,
        product_id: str,
        variants: Sequence[NewVariant],
        lookup: OptionLookup,
    ) -> None:
        skus: set[str] = set()
        combinations: set[frozenset[tuple[str, str]]] = set()
        for position, variant in enumerate(variants):
            clean = clean_variant(variant, lookup)
            if clean.sku.lower() in skus:
                raise CatalogueConflict(CONFLICTS["uq_variants_sku_lower"])
            if clean.combination in combinations:
                raise CatalogueConflict("Two variants have the same options")
            skus.add(clean.sku.lower())
            combinations.add(clean.combination)
            await self._insert_variant(product_id, clean, position)

    async def _insert_variant(
        self, product_id: str, clean: CleanVariant, position: int
    ) -> None:
        variant_id = new_id()
        await self._repository.insert_variant(
            variant_id=variant_id,
            product_id=product_id,
            sku=clean.sku,
            price_minor=clean.money.price_minor,
            compare_at_price_minor=clean.money.compare_at_price_minor,
            weight_grams=clean.weight_grams,
            stock=clean.stock,
            position=position,
        )
        for option_id, value_id in clean.choices.items():
            await self._repository.insert_variant_choice(
                variant_id=variant_id,
                option_id=option_id,
                option_value_id=value_id,
                product_id=product_id,
            )
