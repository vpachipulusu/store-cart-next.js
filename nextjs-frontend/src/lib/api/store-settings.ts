import 'server-only';

import { BACKEND_ERROR_MESSAGE, callBackend, type ApiResult } from './server';
import {
  getStoreSettings,
  updateStoreSettings,
  type StoreSettingsResponse,
  type UpdateStoreSettingsRequest,
} from './generated';

/**
 * Server-only calls to the merchant store settings API (KAN-82, KAN-83): shipping and tax of one store. Callers
 * import these instead of the generated SDK (ADR-008). The store id must come from `getCurrentStoreSelection()`,
 * never from the browser; the backend authorizes it and the role again on every call.
 *
 * Only the backend's own 404 and 422 messages are shown; every other failure becomes a fixed message here.
 */

export const STORE_SETTINGS_UNAVAILABLE_MESSAGE =
  'Store settings could not be reached. Please try again.';
export const STORE_SETTINGS_FORBIDDEN_MESSAGE =
  'You do not have permission to change settings in this store.';
export const STORE_SETTINGS_SESSION_MESSAGE = 'Your session has expired. Sign in again.';
export const STORE_SETTINGS_RATE_LIMITED_MESSAGE =
  'Too many requests. Wait a moment and try again.';
export const STORE_SETTINGS_FAILED_MESSAGE = 'The request failed. Please try again.';

export type { StoreSettingsResponse };

const CURATED_STATUSES: ReadonlySet<number> = new Set([404, 422]);
const CURATED_MAX_LENGTH = 200;

function isCurated(text: string): boolean {
  return text !== '' && text !== BACKEND_ERROR_MESSAGE && text.length <= CURATED_MAX_LENGTH;
}

/** The message to show for a failed result. */
export function storeSettingsErrorMessage(result: { error: string; status?: number }): string {
  const { status } = result;
  if (status === undefined) return STORE_SETTINGS_UNAVAILABLE_MESSAGE;
  if (CURATED_STATUSES.has(status) && isCurated(result.error)) return result.error;
  if (status === 401) return STORE_SETTINGS_SESSION_MESSAGE;
  if (status === 403) return STORE_SETTINGS_FORBIDDEN_MESSAGE;
  if (status === 429) return STORE_SETTINGS_RATE_LIMITED_MESSAGE;
  if (status === 503) return STORE_SETTINGS_UNAVAILABLE_MESSAGE;
  return STORE_SETTINGS_FAILED_MESSAGE;
}

/** The body has no `success` flag, so `callBackend` passes it whole; refuse any other shape. */
function asSettings(data: unknown): ApiResult<StoreSettingsResponse> {
  if (
    !data ||
    typeof data !== 'object' ||
    Array.isArray(data) ||
    !('tax_rate_bps' in data) ||
    !('shipping_flat_rate_minor' in data)
  ) {
    return { success: false, error: STORE_SETTINGS_FAILED_MESSAGE, status: 502 };
  }
  return { success: true, data: data as StoreSettingsResponse };
}

export async function fetchStoreSettings(
  storeId: string
): Promise<ApiResult<StoreSettingsResponse>> {
  const result = await callBackend((client) =>
    getStoreSettings({ client, path: { store_id: storeId } })
  );
  return result.success ? asSettings(result.data) : result;
}

export async function saveStoreSettings(
  storeId: string,
  body: UpdateStoreSettingsRequest
): Promise<ApiResult<StoreSettingsResponse>> {
  const result = await callBackend((client) =>
    updateStoreSettings({ client, path: { store_id: storeId }, body })
  );
  return result.success ? asSettings(result.data) : result;
}
