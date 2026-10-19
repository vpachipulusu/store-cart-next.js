'use server';

import { revalidatePath } from 'next/cache';
import {
  saveStoreSettings,
  storeSettingsErrorMessage,
  type StoreSettingsResponse,
} from '@/lib/api/store-settings';
import { logger } from '@/lib/logger';
import { getCurrentStoreSelection } from '@/lib/stores/current';
import { STORES_UNAVAILABLE_MESSAGE } from '@/lib/stores/selection';
import { storeSettingsSchema, type StoreSettingsInput } from '@/lib/store-settings/form';

/**
 * Store shipping and tax action (KAN-82, KAN-83). The store comes from `getCurrentStoreSelection()` on the
 * server, never from the browser, and the backend authorizes it again for the caller's role. Input is validated
 * with the same Zod schema the form uses.
 */

export type StoreSettingsActionResponse =
  | { success: true; data: StoreSettingsResponse; error?: undefined }
  | { success: false; data?: undefined; error: string };

const STORE_CHANGED_MESSAGE = 'The selected store changed. Reload.';
const NO_STORE_MESSAGE = 'Select a store before changing its settings.';
const INVALID_INPUT_MESSAGE = 'Check the highlighted fields and try again.';

export async function updateStoreSettingsAction(
  input: StoreSettingsInput
): Promise<StoreSettingsActionResponse> {
  const parsed = storeSettingsSchema.safeParse(input);
  if (!parsed.success) return { success: false, error: INVALID_INPUT_MESSAGE };

  const selection = await getCurrentStoreSelection();
  if (!selection.available) return { success: false, error: STORES_UNAVAILABLE_MESSAGE };
  if (!selection.selected) return { success: false, error: NO_STORE_MESSAGE };

  const value = parsed.data;
  if (selection.selected.id !== value.storeId) {
    return { success: false, error: STORE_CHANGED_MESSAGE };
  }
  const result = await saveStoreSettings(selection.selected.id, {
    shipping_flat_rate_minor: value.shippingFlatRateMinor,
    free_shipping_threshold_minor: value.freeShippingThresholdMinor,
    tax_rate_bps: value.taxRateBps,
    prices_include_tax: value.pricesIncludeTax,
  });
  if (!result.success) {
    logger.warn('Store settings action failed', { status: result.status });
    return { success: false, error: storeSettingsErrorMessage(result) };
  }
  revalidatePath('/dashboard/settings/store');
  return { success: true, data: result.data };
}
