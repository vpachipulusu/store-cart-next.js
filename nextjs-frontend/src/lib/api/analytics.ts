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
export const ANALYTICS_ACCESS_DENIED_MESSAGE = 'You do not have access to these analytics.';

/** `require_merchant`'s fixed 403 body for a role outside OWNER and ADMIN; other 403s (e.g. email) differ. */
const ROLE_REFUSED_ERROR = 'Forbidden';

const CURATED_MAX_LENGTH = 200;

export { ANALYTICS_FORBIDDEN_MESSAGE };
export type { CurrencyAnalyticsData, SalesPointData, StoreAnalyticsData, TopProductData };

/** The backend refused the caller's role (STAFF), as opposed to any other 403. */
export function isRoleRefusal(result: { error: string; status?: number }): boolean {
  return result.status === 403 && result.error === ROLE_REFUSED_ERROR;
}

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
  if (status === 403) {
    return isRoleRefusal(result) ? ANALYTICS_FORBIDDEN_MESSAGE : ANALYTICS_ACCESS_DENIED_MESSAGE;
  }
  if (status === 429) return ANALYTICS_RATE_LIMITED_MESSAGE;
  if (status === 503) return ANALYTICS_UNAVAILABLE_MESSAGE;
  return ANALYTICS_REQUEST_FAILED_MESSAGE;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const isInt = (value: unknown): value is number => Number.isSafeInteger(value);

function isTotals(value: unknown): boolean {
  return (
    isRecord(value) &&
    isInt(value.orders) &&
    isInt(value.gross_sales_minor) &&
    isInt(value.refunds_minor) &&
    isInt(value.net_sales_minor)
  );
}

function isPoint(value: unknown): boolean {
  return isTotals(value) && isRecord(value) && typeof value.bucket_start === 'string';
}

function isProduct(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.product_name === 'string' &&
    isInt(value.units) &&
    isInt(value.revenue_minor)
  );
}

const isListOf = (value: unknown, check: (item: unknown) => boolean): boolean =>
  Array.isArray(value) && value.every(check);

function isCurrencyEntry(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.currency === 'string' &&
    isTotals(value.totals) &&
    isListOf(value.series, isPoint) &&
    isListOf(value.top_products_by_revenue, isProduct) &&
    isListOf(value.top_products_by_units, isProduct)
  );
}

/** Every field the page reads is checked, so a shape drift is a 502 message instead of NaN on screen. */
function isReport(value: unknown): value is StoreAnalyticsData {
  return (
    isRecord(value) &&
    typeof value.start_date === 'string' &&
    typeof value.end_date === 'string' &&
    typeof value.bucket === 'string' &&
    isListOf(value.currencies, isCurrencyEntry)
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
