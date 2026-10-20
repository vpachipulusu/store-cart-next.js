import 'server-only';

import { cookies } from 'next/headers';
import { callBackend, type ApiResult } from './server';
import { startCheckout } from './generated';
import { cartCookieName, isCartToken } from '@/lib/storefront/cart-cookie';
import { checkoutReturnUrls, isStripeCheckoutUrl } from '@/lib/storefront/checkout-url';
import { logger } from '@/lib/logger';
import { isValidStoreSlug } from '@/lib/storefront/host';
import { originFor } from '@/lib/storefront/store-origin';

/**
 * Server-only call to the storefront checkout (KAN-68) for one store, keyed by the shopper's store-scoped cart
 * cookie. Callers import this instead of the generated SDK (ADR-008). The backend creates the pending order and a
 * Stripe Checkout Session; only the Connect webhook ever marks the order paid. The shopper's session is never
 * forwarded, the cart cookie is not changed, and backend error text (which can mention Stripe) never reaches the
 * shopper: every failure becomes a fixed message.
 */

export const CHECKOUT_NOT_FOUND_MESSAGE = 'Store not found.';
export const CHECKOUT_CART_CHANGED_MESSAGE =
  'Your basket has changed or is not ready for checkout. Please review it and try again.';
export const CHECKOUT_INVALID_RETURN_MESSAGE =
  'Checkout could not be started from this address. Please try again from the store.';
export const CHECKOUT_RATE_LIMITED_MESSAGE = 'Too many requests. Wait a moment and try again.';
export const CHECKOUT_PAYMENTS_UNAVAILABLE_MESSAGE =
  'Payments are unavailable right now. Please try again shortly.';
export const CHECKOUT_FAILED_MESSAGE = 'Checkout could not be started. Please try again.';

/** The shopper message for a backend status (`undefined` when the backend could not be reached). */
export function checkoutErrorMessage(status: number | undefined): string {
  switch (status) {
    case undefined:
    case 502:
    case 503:
      return CHECKOUT_PAYMENTS_UNAVAILABLE_MESSAGE;
    case 404:
      return CHECKOUT_NOT_FOUND_MESSAGE;
    case 409:
      return CHECKOUT_CART_CHANGED_MESSAGE;
    case 422:
      return CHECKOUT_INVALID_RETURN_MESSAGE;
    case 429:
      return CHECKOUT_RATE_LIMITED_MESSAGE;
    default:
      return CHECKOUT_FAILED_MESSAGE;
  }
}

export type CheckoutStart = ApiResult<{ checkoutUrl: string }>;

/** Starts a checkout for the shopper's cart in this store; the caller redirects to `checkoutUrl`. */
export async function beginCheckout(slug: string): Promise<CheckoutStart> {
  if (!isValidStoreSlug(slug)) {
    return { success: false, error: CHECKOUT_NOT_FOUND_MESSAGE, status: 404 };
  }
  const cookieValue = (await cookies()).get(cartCookieName(slug))?.value;
  const { successUrl, cancelUrl } = checkoutReturnUrls(originFor(slug));
  const result = await callBackend(
    (client) =>
      startCheckout({
        client,
        path: { slug },
        headers: isCartToken(cookieValue) ? { 'X-Cart-Token': cookieValue } : {},
        body: { success_url: successUrl, cancel_url: cancelUrl },
      }),
    { withSession: false }
  );
  if (!result.success) {
    // The shopper gets a fixed message; the backend status is kept for the logs (never the cart token).
    logger.warn('Storefront checkout refused', { slug, status: result.status });
    return { success: false, error: checkoutErrorMessage(result.status), status: result.status };
  }
  if (!isStripeCheckoutUrl(result.data.checkout_url)) {
    logger.error('Storefront checkout returned a URL that is not Stripe-hosted', { slug });
    return { success: false, error: CHECKOUT_FAILED_MESSAGE, status: 502 };
  }
  return { success: true, data: { checkoutUrl: result.data.checkout_url } };
}
