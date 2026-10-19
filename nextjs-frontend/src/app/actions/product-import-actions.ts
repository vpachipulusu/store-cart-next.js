'use server';

import { revalidatePath } from 'next/cache';
import { importStoreProducts, productErrorMessage } from '@/lib/api/products';
import { logger } from '@/lib/logger';
import { csvFileSchema, TOO_LARGE_MESSAGE, type ImportOutcome } from '@/lib/products/csv-import';
import { isEntityId } from '@/lib/products/schema';
import { getCurrentStoreSelection } from '@/lib/stores/current';
import { STORES_UNAVAILABLE_MESSAGE } from '@/lib/stores/selection';

/**
 * Product CSV import (KAN-74). The store is the one `getCurrentStoreSelection()` resolves on the server; the
 * `storeId` the dialog was rendered with must match it, so a store switched in another tab never receives a file
 * meant for the old one. The backend authorizes the store and the role again and checks every row; its per-row
 * problems come back as data, not as an error.
 */

export type ImportActionResponse =
  | { success: true; data: ImportOutcome; error?: undefined }
  | { success: false; data?: undefined; error: string };

const NO_STORE_MESSAGE = 'Select a store before importing products.';
const STORE_CHANGED_MESSAGE = 'The selected store changed. Reload the page and try again.';

function fail(error: string): ImportActionResponse {
  return { success: false, error };
}

export async function importProductsAction(
  storeId: string,
  formData: FormData
): Promise<ImportActionResponse> {
  if (!isEntityId(storeId)) return fail(STORE_CHANGED_MESSAGE);
  const file = csvFileSchema.safeParse(formData.get('file'));
  if (!file.success) return fail(file.error.issues[0]?.message ?? 'Choose a CSV file.');

  const selection = await getCurrentStoreSelection();
  if (!selection.available) return fail(STORES_UNAVAILABLE_MESSAGE);
  if (!selection.selected) return fail(NO_STORE_MESSAGE);
  if (selection.selected.id !== storeId) return fail(STORE_CHANGED_MESSAGE);

  const result = await importStoreProducts(selection.selected.id, file.data);
  if (!result.success) {
    logger.warn('Product import failed', { status: result.status });
    return fail(result.status === 413 ? TOO_LARGE_MESSAGE : productErrorMessage(result));
  }
  if (result.data.imported > 0) revalidatePath('/dashboard/products');
  return { success: true, data: result.data };
}
