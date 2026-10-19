import { z } from 'zod';

/**
 * Merchant order input and labels (KAN-79). Pure, so the fulfilment form and the server action share one
 * definition. Limits mirror the backend (backend-store-orders.md); the backend stays the authority.
 */
export const ORDER_STATUSES = ['pending', 'paid', 'fulfilled', 'cancelled', 'refunded'] as const;
export type OrderStatus = (typeof ORDER_STATUSES)[number];

export const ORDER_STATUS_LABELS: Record<OrderStatus, string> = {
  pending: 'Pending',
  paid: 'Paid',
  fulfilled: 'Fulfilled',
  cancelled: 'Cancelled',
  refunded: 'Refunded',
};

export const TRACKING_MAX_LENGTH = 100;

const CONTROL_CHARACTERS = /[\p{Cc}\p{Bidi_Control}]/u;

const trackingText = (label: string) =>
  z
    .string()
    .trim()
    .max(TRACKING_MAX_LENGTH, `${label} must be ${TRACKING_MAX_LENGTH} characters or fewer`)
    .refine((value) => !CONTROL_CHARACTERS.test(value), `${label} contains invalid characters`);

export const fulfilOrderSchema = z.object({
  trackingNumber: trackingText('Tracking number').refine(
    (value) => value.length > 0,
    'Tracking number is required'
  ),
  /** Empty text or null both mean "no carrier". */
  carrier: trackingText('Carrier')
    .nullish()
    .transform((value) => value || null),
});

export type FulfilOrderInput = z.input<typeof fulfilOrderSchema>;
export type FulfilOrderValues = z.output<typeof fulfilOrderSchema>;

/** Ids are opaque strings; this only screens out junk before the backend (which owns the real check). */
const ORDER_ID_PATTERN = /^[A-Za-z0-9_-]{1,100}$/;

export function isOrderId(value: unknown): value is string {
  return typeof value === 'string' && ORDER_ID_PATTERN.test(value);
}

export function isOrderStatus(value: unknown): value is OrderStatus {
  return typeof value === 'string' && (ORDER_STATUSES as readonly string[]).includes(value);
}
