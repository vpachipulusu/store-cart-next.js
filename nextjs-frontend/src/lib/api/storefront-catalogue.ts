import 'server-only';

import { unstable_cache } from 'next/cache';
import { callBackend, type ApiResult, type BackendOptions } from './server';
import {
  listStorefrontCategories,
  listStorefrontProducts,
  readStorefront,
  readStorefrontProduct,
  type PublicCategoryData,
  type PublicImageData,
  type PublicProductData,
  type PublicProductListResponse,
} from './generated';
import { isValidStoreSlug } from '@/lib/storefront/host';
import {
  PAGE_SIZE,
  pageCount,
  type ProductDetail,
  type ProductPage,
  type StoreCategory,
  type StoreImage,
} from '@/lib/storefront/catalogue';
import {
  STOREFRONT_REVALIDATE_SECONDS,
  storefrontCacheKey,
  storefrontTag,
} from '@/lib/storefront/cache';
import type { PublicStorefront } from './storefront';

/**
 * Server-only public catalogue reads for the storefront pages (KAN-75, backend
 * `/v1/storefront/{slug}/products|categories`). Only published products of an ACTIVE store come back.
 *
 * Reads that every visitor shares are cached per store with `unstable_cache`, tagged `storefront:{slug}` and
 * revalidated when the merchant changes the catalogue (or after STOREFRONT_REVALIDATE_SECONDS). Those calls send
 * no session and no visitor IP (`shared`), so the backend rate-limits cache misses by the server's address.
 * Search is not cached (any text is a new key) and forwards the visitor's IP like the cart.
 *
 * A missing store, product or category reads as `null`. Any other failure throws, so it is never cached and an
 * outage is an error page, not a "not found".
 */

export const STOREFRONT_UNAVAILABLE_MESSAGE = 'Storefront temporarily unavailable';

function image(data: PublicImageData, fallbackAlt: string): StoreImage {
  return { url: data.url, alt: data.alt_text?.trim() || fallbackAlt };
}

export function mapCategory(data: PublicCategoryData): StoreCategory {
  return { name: data.name, slug: data.slug, parentSlug: data.parent_slug };
}

export function mapProductPage(data: PublicProductListResponse, page: number): ProductPage {
  return {
    items: data.data.map((item) => ({
      title: item.title,
      slug: item.slug,
      minPriceMinor: item.min_price_minor,
      maxPriceMinor: item.max_price_minor,
      image: item.image ? image(item.image, item.title) : null,
    })),
    currency: data.currency,
    total: data.total,
    page,
    pageCount: pageCount(data.total, PAGE_SIZE),
  };
}

export function mapProduct(data: PublicProductData): ProductDetail {
  return {
    title: data.title,
    slug: data.slug,
    description: data.description,
    currency: data.currency,
    options: data.options.map((option) => ({
      name: option.name,
      values: option.values.map((value) => ({ id: value.id, value: value.value })),
    })),
    variants: data.variants.map((variant) => ({
      id: variant.id,
      priceMinor: variant.price_minor,
      compareAtPriceMinor: variant.compare_at_price_minor,
      inStock: variant.in_stock,
      optionValueIds: variant.option_value_ids,
    })),
    images: data.images.map((item, index) =>
      image(item, index === 0 ? data.title : `${data.title}, image ${index + 1}`)
    ),
    categories: data.categories.map(mapCategory),
  };
}

/** The value, null for a 404, or a thrown error for anything else (never cached). */
function orNull<T, R>(result: ApiResult<T>, map: (data: T) => R): R | null {
  if (result.success) return map(result.data);
  if (result.status === 404) return null;
  throw new Error(STOREFRONT_UNAVAILABLE_MESSAGE);
}

function cached<A extends unknown[], R>(
  read: string,
  load: (slug: string, ...args: A) => Promise<R | null>
): (slug: string, ...args: A) => Promise<R | null> {
  return (slug, ...args) => {
    if (!isValidStoreSlug(slug)) return Promise.resolve(null);
    return unstable_cache(
      () => load(slug, ...args),
      storefrontCacheKey(read, slug, ...(args as (string | number | null)[])),
      { tags: [storefrontTag(slug)], revalidate: STOREFRONT_REVALIDATE_SECONDS }
    )();
  };
}

const SHARED: BackendOptions = { shared: true };

interface ListQuery {
  category?: string | null;
  query?: string | null;
  page: number;
}

async function loadProducts(
  slug: string,
  { category, query, page }: ListQuery,
  options: BackendOptions
): Promise<ProductPage | null> {
  // Boxed so the generic unwrap (which strips `{ data }` envelopes) keeps the currency and totals.
  const result = await callBackend(async (client) => {
    const reply = await listStorefrontProducts({
      client,
      path: { slug },
      query: {
        category: category || undefined,
        q: query || undefined,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      },
    });
    return { ...reply, data: reply.data ? { page: reply.data } : undefined };
  }, options);
  return orNull(result, (data) => mapProductPage(data.page, page));
}

/** The public store (name and slug), cached per store. */
export const getPublicStore = cached(
  'store',
  async (slug: string): Promise<PublicStorefront | null> => {
    const result = await callBackend((client) => readStorefront({ client, path: { slug } }), SHARED);
    return orNull(result, (data) => ({ name: data.name, slug: data.slug }));
  }
);

/** Newest published products, optionally in one category (by slug); null for an unknown category or store. */
export const getProductPage = cached(
  'products',
  (slug: string, category: string | null, page: number) =>
    loadProducts(slug, { category, page }, SHARED)
);

export const getProduct = cached(
  'product',
  async (slug: string, productSlug: string): Promise<ProductDetail | null> => {
    const result = await callBackend(
      (client) => readStorefrontProduct({ client, path: { slug, product_slug: productSlug } }),
      SHARED
    );
    return orNull(result, mapProduct);
  }
);

export const getCategories = cached(
  'categories',
  async (slug: string): Promise<StoreCategory[] | null> => {
    const result = await callBackend(
      (client) => listStorefrontCategories({ client, path: { slug } }),
      SHARED
    );
    return orNull(result, (data) => data.map(mapCategory));
  }
);

/** Uncached search; forwards the visitor's IP so each shopper has their own rate limit. */
export async function searchProducts(
  slug: string,
  query: string,
  page: number
): Promise<ProductPage | null> {
  if (!isValidStoreSlug(slug)) return null;
  return loadProducts(slug, { query, page }, { withSession: false });
}
