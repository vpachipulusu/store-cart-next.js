import 'server-only';

import { BACKEND_ERROR_MESSAGE, callBackend, type ApiResult } from './server';
import type { Client } from './generated/client';
import {
  fulfilOrder,
  listOrders,
  readOrder,
  type OrderData,
  type OrderListResponse,
} from './generated';
import type { OrderStatus } from '@/lib/orders/schema';

/**
 * Server-only calls to the merchant order API (KAN-79) for the order screens and the fulfil action. Callers import
 * these instead of the generated SDK (ADR-008). The backend authorizes the store id and the role on every call;
 * the store id passed in must come from `getCurrentStoreSelection()`, never from the browser.
 *
 * 404, 409 and 422 messages are curated by the backend, so they are shown as they are. Every other failure becomes
 * a fixed message here; backend text for those is never forwarded.
 */

export const ORDERS_PAGE_SIZE = 25;

export const ORDER_UNAVAILABLE_MESSAGE = 'Orders could not be reached. Please try again.';
export const ORDER_FORBIDDEN_MESSAGE = 'You do not have permission to do that in this store.';
export const ORDER_SESSION_MESSAGE = 'Your session has expired. Sign in again.';
export const ORDER_RATE_LIMITED_MESSAGE = 'Too many requests. Wait a moment and try again.';
export const ORDER_REQUEST_FAILED_MESSAGE = 'The request failed. Please try again.';

const CURATED_STATUSES: ReadonlySet<number> = new Set([404, 409, 422]);
const CURATED_MAX_LENGTH = 200;

function isCurated(text: string): boolean {
  return text !== '' && text !== BACKEND_ERROR_MESSAGE && text.length <= CURATED_MAX_LENGTH;
}

/** The message to show for a failed result. */
export function orderErrorMessage(result: { error: string; status?: number }): string {
  const { status } = result;
  if (status === undefined) return ORDER_UNAVAILABLE_MESSAGE;
  if (CURATED_STATUSES.has(status) && isCurated(result.error)) return result.error;
  if (status === 401) return ORDER_SESSION_MESSAGE;
  if (status === 403) return ORDER_FORBIDDEN_MESSAGE;
  if (status === 429) return ORDER_RATE_LIMITED_MESSAGE;
  if (status === 503) return ORDER_UNAVAILABLE_MESSAGE;
  return ORDER_REQUEST_FAILED_MESSAGE;
}

export type { OrderData, OrderListResponse };

export type OrderListQuery = {
  status?: OrderStatus;
  limit?: number;
  offset?: number;
};

type OrderBody = { data: OrderData } | OrderData;

function isObjectBody(body: unknown): body is OrderBody {
  return typeof body === 'object' && body !== null && !Array.isArray(body);
}

/** Order responses are `{ data: order }` without the `success` flag `callBackend` unwraps. */
async function callOrder(
  call: (client: Client) => Promise<{ data?: OrderBody; error?: unknown; response?: Response }>
): Promise<ApiResult<OrderData>> {
  const result = await callBackend(call);
  if (!result.success) return result;
  const body: unknown = result.data;
  if (!isObjectBody(body)) {
    return { success: false, error: ORDER_REQUEST_FAILED_MESSAGE, status: 502 };
  }
  const order = 'data' in body ? body.data : body;
  if (!order || typeof order.id !== 'string' || !Array.isArray(order.items)) {
    return { success: false, error: ORDER_REQUEST_FAILED_MESSAGE, status: 502 };
  }
  return { success: true, data: order };
}

export async function fetchOrders(
  storeId: string,
  query: OrderListQuery = {}
): Promise<ApiResult<OrderListResponse>> {
  const result = await callBackend((client) =>
    listOrders({
      client,
      path: { store_id: storeId },
      query: {
        status: query.status,
        limit: query.limit ?? ORDERS_PAGE_SIZE,
        offset: query.offset ?? 0,
      },
    })
  );
  if (!result.success) return result;
  // The list body has no `success` flag, so callBackend passes it through whole; refuse any other shape.
  const body = result.data as unknown;
  if (!body || typeof body !== 'object' || Array.isArray(body) || !('total' in body)) {
    return { success: false, error: ORDER_REQUEST_FAILED_MESSAGE, status: 502 };
  }
  const list = body as OrderListResponse;
  if (!Array.isArray(list.data) || typeof list.total !== 'number') {
    return { success: false, error: ORDER_REQUEST_FAILED_MESSAGE, status: 502 };
  }
  return { success: true, data: list };
}

export async function fetchOrder(storeId: string, orderId: string): Promise<ApiResult<OrderData>> {
  return callOrder((client) =>
    readOrder({ client, path: { store_id: storeId, order_id: orderId } })
  );
}

export async function fulfilStoreOrder(
  storeId: string,
  orderId: string,
  body: { trackingNumber: string; carrier: string | null }
): Promise<ApiResult<OrderData>> {
  return callOrder((client) =>
    fulfilOrder({
      client,
      path: { store_id: storeId, order_id: orderId },
      body: { tracking_number: body.trackingNumber, carrier: body.carrier },
    })
  );
}
