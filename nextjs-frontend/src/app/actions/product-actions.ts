'use server';

import { revalidatePath } from 'next/cache';
import type { ZodType, ZodTypeDef } from 'zod';
import {
  addProductImage,
  addProductVariant,
  createStoreProduct,
  deleteProductImage,
  deleteProductVariant,
  deleteStoreProduct,
  PRODUCT_REQUEST_FAILED_MESSAGE,
  presignProductImage,
  productErrorMessage,
  updateProductVariant,
  updateStoreProduct,
  type ProductData,
} from '@/lib/api/products';
import { logger } from '@/lib/logger';
import { getCurrentStoreSelection } from '@/lib/stores/current';
import { refreshStorefront, type StorefrontChange } from '@/lib/storefront/revalidate';
import { STORES_UNAVAILABLE_MESSAGE } from '@/lib/stores/selection';
import { altTextSchema, isStoreImageKey, presignRequestSchema } from '@/lib/products/image-upload';
import {
  createProductSchema,
  fieldErrors,
  isEntityId,
  productDetailsSchema,
  variantSchema,
  type CreateProductInput,
  type ProductDetailsInput,
  type VariantInput,
} from '@/lib/products/schema';

/**
 * Merchant product actions (KAN-73). The store comes from `getCurrentStoreSelection()` on the server, never from
 * the browser, and the backend authorizes it again for the caller's role. Input is validated with the same Zod
 * schemas the forms use. Backend 404/409/422 text is curated and shown; any other failure becomes a fixed message.
 */

export type ProductActionResponse<T = ProductData> =
  | { success: true; data: T; error?: undefined; fieldErrors?: undefined }
  | {
      success: false;
      data?: undefined;
      error: string;
      fieldErrors?: Record<string, string>;
    };

const NO_STORE_MESSAGE = 'Select a store before managing products.';
const INVALID_INPUT_MESSAGE = 'Check the highlighted fields and try again.';
const INVALID_ID_MESSAGE = 'That item could not be found.';
const INVALID_IMAGE_KEY_MESSAGE =
  'That upload does not belong to this store. Choose the image again.';

type Resolved = { ok: true; storeId: string; storeSlug: string } | { ok: false; error: string };

async function resolveStore(): Promise<Resolved> {
  const selection = await getCurrentStoreSelection();
  if (!selection.available) return { ok: false, error: STORES_UNAVAILABLE_MESSAGE };
  if (!selection.selected) return { ok: false, error: NO_STORE_MESSAGE };
  return { ok: true, storeId: selection.selected.id, storeSlug: selection.selected.slug };
}

function fail(error: string, fields?: Record<string, string>): ProductActionResponse<never> {
  return { success: false, error, fieldErrors: fields };
}

function parse<T>(schema: ZodType<T, ZodTypeDef, unknown>, input: unknown) {
  const parsed = schema.safeParse(input);
  return parsed.success
    ? ({ ok: true, value: parsed.data } as const)
    : ({ ok: false, response: fail(INVALID_INPUT_MESSAGE, fieldErrors(parsed.error)) } as const);
}

/** Refreshes the dashboard and this store's cached storefront pages (KAN-75). */
function refresh(storeSlug: string, change: StorefrontChange, productId?: string): void {
  revalidatePath('/dashboard/products');
  if (productId) revalidatePath(`/dashboard/products/${productId}`);
  refreshStorefront(storeSlug, change);
}

function backendFailure(
  action: string,
  result: { error: string; status?: number }
): ProductActionResponse<never> {
  logger.warn('Product action failed', { action, status: result.status });
  return fail(productErrorMessage(result));
}

export async function createProductAction(
  input: CreateProductInput
): Promise<ProductActionResponse> {
  const parsed = parse(createProductSchema, input);
  if (!parsed.ok) return parsed.response;
  const store = await resolveStore();
  if (!store.ok) return fail(store.error);

  const { value } = parsed;
  const result = await createStoreProduct(store.storeId, {
    title: value.title,
    slug: value.slug,
    description: value.description,
    status: value.status,
    category_ids: value.categoryIds,
    options: value.options,
    variants: value.variants.map(toVariantBody),
  });
  if (!result.success) return backendFailure('create', result);
  refresh(store.storeSlug, 'edit');
  return { success: true, data: result.data };
}

function toVariantBody(variant: VariantInput) {
  return {
    sku: variant.sku,
    price_minor: variant.priceMinor,
    compare_at_price_minor: variant.compareAtPriceMinor,
    weight_grams: variant.weightGrams,
    stock: variant.stock,
    options: variant.options,
  };
}

export async function updateProductAction(
  productId: string,
  input: ProductDetailsInput
): Promise<ProductActionResponse> {
  if (!isEntityId(productId)) return fail(INVALID_ID_MESSAGE);
  const parsed = parse(productDetailsSchema, input);
  if (!parsed.ok) return parsed.response;
  const store = await resolveStore();
  if (!store.ok) return fail(store.error);

  const { value } = parsed;
  const result = await updateStoreProduct(store.storeId, productId, {
    title: value.title,
    // An empty slug is left alone: the backend keeps the existing one (null would be rejected).
    ...(value.slug ? { slug: value.slug } : {}),
    description: value.description,
    status: value.status,
    category_ids: value.categoryIds,
  });
  if (!result.success) return backendFailure('update', result);
  refresh(store.storeSlug, value.status === 'draft' ? 'remove' : 'edit', productId);
  return { success: true, data: result.data };
}

export async function deleteProductAction(
  productId: string
): Promise<ProductActionResponse<{ deleted: true }>> {
  if (!isEntityId(productId)) return fail(INVALID_ID_MESSAGE);
  const store = await resolveStore();
  if (!store.ok) return fail(store.error);

  const result = await deleteStoreProduct(store.storeId, productId);
  if (!result.success) return backendFailure('delete', result);
  refresh(store.storeSlug, 'remove');
  return { success: true, data: { deleted: true } };
}

export async function addVariantAction(
  productId: string,
  input: VariantInput
): Promise<ProductActionResponse> {
  if (!isEntityId(productId)) return fail(INVALID_ID_MESSAGE);
  const parsed = parse(variantSchema, input);
  if (!parsed.ok) return parsed.response;
  const store = await resolveStore();
  if (!store.ok) return fail(store.error);

  const result = await addProductVariant(store.storeId, productId, toVariantBody(parsed.value));
  if (!result.success) return backendFailure('add-variant', result);
  refresh(store.storeSlug, 'edit', productId);
  return { success: true, data: result.data };
}

export async function updateVariantAction(
  productId: string,
  variantId: string,
  input: VariantInput
): Promise<ProductActionResponse> {
  if (!isEntityId(productId) || !isEntityId(variantId)) return fail(INVALID_ID_MESSAGE);
  const parsed = parse(variantSchema, input);
  if (!parsed.ok) return parsed.response;
  const store = await resolveStore();
  if (!store.ok) return fail(store.error);

  const { sku, price_minor, compare_at_price_minor, weight_grams, stock } = toVariantBody(
    parsed.value
  );
  const result = await updateProductVariant(store.storeId, productId, variantId, {
    sku,
    price_minor,
    compare_at_price_minor,
    weight_grams,
    stock,
  });
  if (!result.success) return backendFailure('update-variant', result);
  refresh(store.storeSlug, 'edit', productId);
  return { success: true, data: result.data };
}

export async function deleteVariantAction(
  productId: string,
  variantId: string
): Promise<ProductActionResponse> {
  if (!isEntityId(productId) || !isEntityId(variantId)) return fail(INVALID_ID_MESSAGE);
  const store = await resolveStore();
  if (!store.ok) return fail(store.error);

  const result = await deleteProductVariant(store.storeId, productId, variantId);
  if (!result.success) return backendFailure('delete-variant', result);
  refresh(store.storeSlug, 'remove', productId);
  return { success: true, data: result.data };
}

export type ImageUploadTicket = { uploadUrl: string; headers: Record<string, string>; key: string };

/** The presigned URL must be https (plain http only for a local test endpoint). */
function isSafeUploadUrl(value: string): boolean {
  try {
    const url = new URL(value);
    if (url.username || url.password) return false;
    if (url.protocol === 'https:') return true;
    return url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  } catch {
    return false;
  }
}

/**
 * Step 1 of an image upload: validates type and size, then asks the backend for a presigned PUT under the
 * selected store's prefix. The browser sends the file straight to storage; the file never passes through here.
 * The returned URL is a credential: it is handed to the caller and never logged.
 */
export async function presignImageUploadAction(
  productId: string,
  input: { contentType: string; sizeBytes: number }
): Promise<ProductActionResponse<ImageUploadTicket>> {
  if (!isEntityId(productId)) return fail(INVALID_ID_MESSAGE);
  const parsed = presignRequestSchema.safeParse(input);
  if (!parsed.success) return fail(parsed.error.issues[0]?.message ?? INVALID_INPUT_MESSAGE);
  const store = await resolveStore();
  if (!store.ok) return fail(store.error);

  const result = await presignProductImage(store.storeId, parsed.data);
  if (!result.success) return backendFailure('presign-image', result);
  const ticket = result.data;
  if (!isStoreImageKey(store.storeId, ticket.key) || !isSafeUploadUrl(ticket.uploadUrl)) {
    logger.warn('Product action failed', { action: 'presign-image', status: 502 });
    return fail(PRODUCT_REQUEST_FAILED_MESSAGE);
  }
  return { success: true, data: ticket };
}

/** Step 3: registers the uploaded object on the product. The key must sit under the selected store's prefix. */
export async function addImageAction(
  productId: string,
  input: { storageKey: string; altText?: string | null }
): Promise<ProductActionResponse> {
  if (!isEntityId(productId)) return fail(INVALID_ID_MESSAGE);
  const alt = altTextSchema.safeParse(input.altText);
  if (!alt.success) {
    return fail(INVALID_INPUT_MESSAGE, { altText: alt.error.issues[0]?.message ?? '' });
  }
  const store = await resolveStore();
  if (!store.ok) return fail(store.error);
  if (!isStoreImageKey(store.storeId, input.storageKey)) return fail(INVALID_IMAGE_KEY_MESSAGE);

  const result = await addProductImage(store.storeId, productId, {
    storage_key: input.storageKey,
    alt_text: alt.data,
  });
  if (!result.success) return backendFailure('add-image', result);
  refresh(store.storeSlug, 'edit', productId);
  return { success: true, data: result.data };
}

export async function deleteImageAction(
  productId: string,
  imageId: string
): Promise<ProductActionResponse> {
  if (!isEntityId(productId) || !isEntityId(imageId)) return fail(INVALID_ID_MESSAGE);
  const store = await resolveStore();
  if (!store.ok) return fail(store.error);

  const result = await deleteProductImage(store.storeId, productId, imageId);
  if (!result.success) return backendFailure('delete-image', result);
  refresh(store.storeSlug, 'edit', productId);
  return { success: true, data: result.data };
}
