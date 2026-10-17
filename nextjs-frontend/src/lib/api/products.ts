import 'server-only';

import { logger } from '@/lib/logger';
import { BACKEND_ERROR_MESSAGE, callBackend, type ApiResult } from './server';
import type { Client } from './generated/client';
import type { CategoryList } from '@/lib/products/categories';
import {
  addVariant,
  createProduct,
  deleteImage,
  deleteProduct,
  deleteVariant,
  listCategories,
  listProducts,
  readProduct,
  updateProduct,
  updateVariant,
  type CategoryListResponse,
  type CreateProductRequest,
  type ProductData,
  type ProductListResponse,
  type UpdateProductRequest,
  type UpdateVariantRequest,
  type VariantBody,
} from './generated';

/**
 * Server-only calls to the merchant product API (KAN-245) for the product screens and actions (KAN-73). Callers
 * import these instead of the generated SDK (ADR-008). The backend authorizes the store id and the role on every
 * call; the store id passed in must come from `getCurrentStoreSelection()`, never from the browser.
 *
 * 404, 409 and 422 messages are curated by the backend (backend-products-api.md), so they are shown as they are.
 * Every other failure becomes a fixed message here; backend text for those is never forwarded.
 */

export const PRODUCTS_PAGE_SIZE = 25;
/** The API rejects `q` over 100 characters (422). */
export const SEARCH_MAX_LENGTH = 100;

export const PRODUCT_UNAVAILABLE_MESSAGE = 'Products could not be reached. Please try again.';
export const PRODUCT_FORBIDDEN_MESSAGE = 'You do not have permission to do that in this store.';
export const PRODUCT_SESSION_MESSAGE = 'Your session has expired. Sign in again.';
export const PRODUCT_RATE_LIMITED_MESSAGE = 'Too many requests. Wait a moment and try again.';
export const PRODUCT_REQUEST_FAILED_MESSAGE = 'The request failed. Please try again.';

type ProductBody = { data: ProductData } | ProductData;

/**
 * Product responses are `{ data: product }` without the `success` flag `callBackend` unwraps, so the product is
 * taken out here. A body that is already the product (or was unwrapped) passes through unchanged.
 */
function isProductBody(body: unknown): body is ProductBody {
  return typeof body === 'object' && body !== null && !Array.isArray(body);
}

async function callProduct(
  call: (client: Client) => Promise<{ data?: ProductBody; error?: unknown; response?: Response }>
): Promise<ApiResult<ProductData>> {
  const result = await callBackend(call);
  if (!result.success) return result;
  const body: unknown = result.data;
  if (!isProductBody(body)) {
    return { success: false, error: PRODUCT_REQUEST_FAILED_MESSAGE, status: 502 };
  }
  return { success: true, data: 'data' in body ? body.data : body };
}

const CURATED_STATUSES: ReadonlySet<number> = new Set([404, 409, 422]);

/** Longest backend message shown; the curated ones are short sentences. */
const CURATED_MAX_LENGTH = 200;

/**
 * Backend text is shown only when it came from the API's own error envelope. A body of another shape (a raw
 * FastAPI/Pydantic 422 with a `detail` list) reaches here as the generic "Request failed" text, which is not
 * shown as if it were a curated message.
 */
function isCurated(text: string): boolean {
  return text !== '' && text !== BACKEND_ERROR_MESSAGE && text.length <= CURATED_MAX_LENGTH;
}

/** The message to show for a failed result. */
export function productErrorMessage(result: { error: string; status?: number }): string {
  const { status } = result;
  if (status === undefined) return PRODUCT_UNAVAILABLE_MESSAGE;
  if (CURATED_STATUSES.has(status) && isCurated(result.error)) return result.error;
  if (status === 401) return PRODUCT_SESSION_MESSAGE;
  if (status === 403) return PRODUCT_FORBIDDEN_MESSAGE;
  if (status === 429) return PRODUCT_RATE_LIMITED_MESSAGE;
  if (status === 503) return PRODUCT_UNAVAILABLE_MESSAGE;
  return PRODUCT_REQUEST_FAILED_MESSAGE;
}

export type { CategoryListResponse, ProductData, ProductListResponse };

export type ProductListQuery = {
  /** Title or SKU text; trimmed by the caller, at most SEARCH_MAX_LENGTH characters. */
  search?: string;
  status?: 'draft' | 'active';
  categoryId?: string;
  limit?: number;
  offset?: number;
};

export async function fetchProducts(
  storeId: string,
  query: ProductListQuery = {}
): Promise<ApiResult<ProductListResponse>> {
  const result = await callBackend((client) =>
    listProducts({
      client,
      path: { store_id: storeId },
      query: {
        q: query.search,
        status: query.status,
        category_id: query.categoryId,
        limit: query.limit ?? PRODUCTS_PAGE_SIZE,
        offset: query.offset ?? 0,
      },
    })
  );
  if (!result.success) return result;
  // The list body has no `success` flag, so callBackend passes it through whole. If the backend ever adds the flag,
  // callBackend would unwrap it to the bare array; refuse that shape instead of crashing the page.
  const body = result.data as unknown;
  if (!body || typeof body !== 'object' || Array.isArray(body) || !('currency' in body)) {
    return { success: false, error: PRODUCT_REQUEST_FAILED_MESSAGE, status: 502 };
  }
  return { success: true, data: body as ProductListResponse };
}

export async function fetchProduct(
  storeId: string,
  productId: string
): Promise<ApiResult<ProductData>> {
  return callProduct((client) =>
    readProduct({ client, path: { store_id: storeId, product_id: productId } })
  );
}

export async function createStoreProduct(
  storeId: string,
  body: CreateProductRequest
): Promise<ApiResult<ProductData>> {
  return callProduct((client) => createProduct({ client, path: { store_id: storeId }, body }));
}

export async function updateStoreProduct(
  storeId: string,
  productId: string,
  body: UpdateProductRequest
): Promise<ApiResult<ProductData>> {
  return callProduct((client) =>
    updateProduct({ client, path: { store_id: storeId, product_id: productId }, body })
  );
}

export async function deleteStoreProduct(
  storeId: string,
  productId: string
): Promise<ApiResult<unknown>> {
  return callBackend((client) =>
    deleteProduct({ client, path: { store_id: storeId, product_id: productId } })
  );
}

export async function addProductVariant(
  storeId: string,
  productId: string,
  body: VariantBody
): Promise<ApiResult<ProductData>> {
  return callProduct((client) =>
    addVariant({ client, path: { store_id: storeId, product_id: productId }, body })
  );
}

export async function updateProductVariant(
  storeId: string,
  productId: string,
  variantId: string,
  body: UpdateVariantRequest
): Promise<ApiResult<ProductData>> {
  return callProduct((client) =>
    updateVariant({
      client,
      path: { store_id: storeId, product_id: productId, variant_id: variantId },
      body,
    })
  );
}

export async function deleteProductVariant(
  storeId: string,
  productId: string,
  variantId: string
): Promise<ApiResult<ProductData>> {
  return callProduct((client) =>
    deleteVariant({
      client,
      path: { store_id: storeId, product_id: productId, variant_id: variantId },
    })
  );
}

export async function deleteProductImage(
  storeId: string,
  productId: string,
  imageId: string
): Promise<ApiResult<ProductData>> {
  return callProduct((client) =>
    deleteImage({
      client,
      path: { store_id: storeId, product_id: productId, image_id: imageId },
    })
  );
}

/** The store's categories, flat. `truncated` means more than 1000 exist and the list is incomplete. */
export async function fetchCategories(storeId: string): Promise<ApiResult<CategoryListResponse>> {
  const result = await callBackend((client) =>
    listCategories({ client, path: { store_id: storeId } })
  );
  if (!result.success) return result;
  // Like the product list, the body has no `success` flag; refuse anything but the documented shape.
  const body = result.data as unknown as Partial<CategoryListResponse> | null;
  if (!body || typeof body !== 'object' || !Array.isArray(body.data)) {
    return { success: false, error: PRODUCT_REQUEST_FAILED_MESSAGE, status: 502 };
  }
  return { success: true, data: { data: body.data, truncated: body.truncated === true } };
}

/** The categories for the screens, or null when they cannot be loaded (the screens then fall back to ids). */
export async function loadCategoryList(storeId: string): Promise<CategoryList | null> {
  const result = await fetchCategories(storeId);
  if (!result.success) logger.error('Products: category list failed', { status: result.status });
  return result.success ? { rows: result.data.data, truncated: result.data.truncated } : null;
}
