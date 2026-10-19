'use server';

import { revalidatePath } from 'next/cache';
import { fulfilStoreOrder, orderErrorMessage, type OrderData } from '@/lib/api/orders';
import { logger } from '@/lib/logger';
import { fieldErrors } from '@/lib/products/schema';
import { fulfilOrderSchema, isOrderId, type FulfilOrderInput } from '@/lib/orders/schema';
import { getCurrentStoreSelection } from '@/lib/stores/current';
import { STORES_UNAVAILABLE_MESSAGE } from '@/lib/stores/selection';

/**
 * Merchant order actions (KAN-79). The store comes from `getCurrentStoreSelection()` on the server, never from
 * the browser, and the backend authorizes it again for the caller's role. Input is validated with the same Zod
 * schema the form uses. Backend 404/409/422 text is curated and shown; any other failure becomes a fixed message.
 */

export type OrderActionResponse =
  | { success: true; data: OrderData; error?: undefined; fieldErrors?: undefined }
  | {
      success: false;
      data?: undefined;
      error: string;
      fieldErrors?: Record<string, string>;
    };

const NO_STORE_MESSAGE = 'Select a store before managing orders.';
const INVALID_INPUT_MESSAGE = 'Check the highlighted fields and try again.';
const INVALID_ID_MESSAGE = 'That order could not be found.';

function fail(error: string, fields?: Record<string, string>): OrderActionResponse {
  return { success: false, error, fieldErrors: fields };
}

export async function fulfilOrderAction(
  orderId: string,
  input: FulfilOrderInput
): Promise<OrderActionResponse> {
  if (!isOrderId(orderId)) return fail(INVALID_ID_MESSAGE);
  const parsed = fulfilOrderSchema.safeParse(input);
  if (!parsed.success) return fail(INVALID_INPUT_MESSAGE, fieldErrors(parsed.error));

  const selection = await getCurrentStoreSelection();
  if (!selection.available) return fail(STORES_UNAVAILABLE_MESSAGE);
  if (!selection.selected) return fail(NO_STORE_MESSAGE);

  const result = await fulfilStoreOrder(selection.selected.id, orderId, parsed.data);
  if (!result.success) {
    logger.warn('Order action failed', { action: 'fulfil', status: result.status });
    return fail(orderErrorMessage(result));
  }
  revalidatePath('/dashboard/orders');
  revalidatePath(`/dashboard/orders/${orderId}`);
  return { success: true, data: result.data };
}
