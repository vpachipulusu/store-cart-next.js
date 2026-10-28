import 'server-only';

import { BACKEND_ERROR_MESSAGE, callBackend, type ApiResult } from './server';
import {
  readStoreAnalytics,
  type CurrencyAnalyticsData,
  type SalesPointData,
  type StoreAnalyticsData,
  type TopProductData,
} from './generated';
import { ANALYTICS_FORBIDDEN_MESSAGE, type AnalyticsQuery } from '@/lib/analytics/query';

/**
 * Server-only call to the merchant analytics API (KAN-96). Callers import this instead of the generated SDK
 * (ADR-008). The backend authorizes the store id and the role (OWNER or ADMIN) on every call; the store id passed
 * in must come from `getCurrentStoreSelection()`, never from the browser.
 *
 * The 422 range message is curated by the backend and shown as it is. Every other failure becomes a fixed message
 * here; 403 is the role state, which the page renders on its own.
 */

export const ANALYTICS_UNAVAILABLE_MESSAGE = 'Analytics could not be reached. Please try again.';
export const ANALYTICS_SESSION_MESSAGE = 'Your session has expired. Sign in again.';
export const ANALYTICS_RATE_LIMITED_MESSAGE = 'Too many requests. Wait a moment and try again.';
export const ANALYTICS_REQUEST_FAILED_MESSAGE = 'The request failed. Please try again.';

const CURATED_MAX_LENGTH = 200;

export { ANALYTICS_FORBIDDEN_MESSAGE };
export type { CurrencyAnalyticsData, SalesPointData, StoreAnalyticsData, TopProductData };

/** The message to show for a failed result. */
export function analyticsErrorMessage(result: { error: string; status?: number }): string {
  const { status, error } = result;
  if (status === undefined) return ANALYTICS_UNAVAILABLE_MESSAGE;
  if (
    status === 422 &&
    error !== '' &&
    error !== BACKEND_ERROR_MESSAGE &&
    error.length <= CURATED_MAX_LENGTH
  ) {
    return error;
  }
  if (status === 401) return ANALYTICS_SESSION_MESSAGE;
  if (status === 403) return ANALYTICS_FORBIDDEN_MESSAGE;
  if (status === 429) return ANALYTICS_RATE_LIMITED_MESSAGE;
  if (status === 503) return ANALYTICS_UNAVAILABLE_MESSAGE;
  return ANALYTICS_REQUEST_FAILED_MESSAGE;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isReport(value: unknown): value is StoreAnalyticsData {
  return (
    isRecord(value) &&
    typeof value.start_date === 'string' &&
    typeof value.end_date === 'string' &&
    typeof value.bucket === 'string' &&
    Array.isArray(value.currencies) &&
    value.currencies.every(
      (entry) =>
        isRecord(entry) &&
        typeof entry.currency === 'string' &&
        isRecord(entry.totals) &&
        Array.isArray(entry.series) &&
        Array.isArray(entry.top_products_by_revenue) &&
        Array.isArray(entry.top_products_by_units)
    )
  );
}

export async function fetchStoreAnalytics(
  storeId: string,
  query: AnalyticsQuery
): Promise<ApiResult<StoreAnalyticsData>> {
  const result = await callBackend((client) =>
    readStoreAnalytics({
      client,
      path: { store_id: storeId },
      query: { from: query.from, to: query.to, bucket: query.bucket },
    })
  );
  if (!result.success) return result;
  // The body is `{ data: report }` without a `success` flag, so callBackend passes it through whole.
  const body: unknown = result.data;
  const report = isRecord(body) ? body.data : undefined;
  if (!isReport(report)) {
    return { success: false, error: ANALYTICS_REQUEST_FAILED_MESSAGE, status: 502 };
  }
  return { success: true, data: report };
}
