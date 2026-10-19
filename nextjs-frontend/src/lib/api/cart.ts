import 'server-only';

import { cookies } from 'next/headers';
import { BACKEND_ERROR_MESSAGE, callBackend, type ApiResult } from './server';
import {
  addCartItem,
  readCart,
  removeCartItem,
  setCartItemQuantity,
  type CartData,
  type CartLineData,
} from './generated';
import { cartCookieName, cartCookieOptions, isCartToken } from '@/lib/storefront/cart-cookie';
import { isValidStoreSlug } from '@/lib/storefront/host';

/**
 * Server-only calls to the public cart API (KAN-76) for one store, keyed by the shopper's store-scoped cookie.
 * Callers import these instead of the generated SDK (ADR-008). The shopper's session is never forwarded. The backend
 * re-prices every request from the catalogue, so a shopper (or a page) can only name a variant and a quantity.
 *
 * A write that starts a cart gets a token back once; it is stored in the httpOnly cookie here and never returned to
 * the caller. 404 and 409 messages are curated by the backend ("Only 3 in stock") and shown as they are; every other
 * failure becomes a fixed message.
 */

export type Cart = Omit<CartData, 'cart_token'>;
export type { CartLineData };

export const CART_UNAVAILABLE_MESSAGE = 'The cart could not be reached. Please try again.';
export const CART_RATE_LIMITED_MESSAGE = 'Too many requests. Wait a moment and try again.';
export const CART_REQUEST_FAILED_MESSAGE = 'The request failed. Please try again.';
export const CART_STORE_NOT_FOUND_MESSAGE = 'Store not found';

const CURATED_STATUSES: ReadonlySet<number> = new Set([404, 409]);
const CURATED_MAX_LENGTH = 200;

/** The message to show for a failed result. */
export function cartErrorMessage(result: { error: string; status?: number }): string {
  const { status } = result;
  if (status === undefined || status === 503) return CART_UNAVAILABLE_MESSAGE;
  if (
    CURATED_STATUSES.has(status) &&
    result.error !== '' &&
    result.error !== BACKEND_ERROR_MESSAGE &&
    result.error.length <= CURATED_MAX_LENGTH
  ) {
    return result.error;
  }
  if (status === 429) return CART_RATE_LIMITED_MESSAGE;
  return CART_REQUEST_FAILED_MESSAGE;
}

type CartResult = ApiResult<Cart>;

async function currentToken(slug: string): Promise<string | undefined> {
  const value = (await cookies()).get(cartCookieName(slug))?.value;
  return isCartToken(value) ? value : undefined;
}

function tokenHeaders(token: string | undefined): { 'X-Cart-Token'?: string } {
  return token ? { 'X-Cart-Token': token } : {};
}

/**
 * Returns the cart without its token. After a write the cookie is (re)set: to a newly issued token, or to the token
 * the shopper sent, so its 30-day lifetime slides with the backend's. Only route handlers and server actions call
 * the write wrappers, since only they may set cookies.
 */
async function finish(
  slug: string,
  result: ApiResult<CartData>,
  sent?: { token: string | undefined }
): Promise<CartResult> {
  if (!result.success) {
    return { success: false, error: cartErrorMessage(result), status: result.status };
  }
  const { cart_token: issued, ...cart } = result.data;
  const keep = isCartToken(issued) ? issued : sent?.token;
  if (sent && keep) {
    (await cookies()).set(cartCookieName(slug), keep, cartCookieOptions());
  }
  return { success: true, data: cart };
}

function badStore(): CartResult {
  return { success: false, error: CART_STORE_NOT_FOUND_MESSAGE, status: 404 };
}

/** The shopper's cart, priced now. Empty (never an error) when there is no cart yet. */
export async function fetchCart(slug: string): Promise<CartResult> {
  if (!isValidStoreSlug(slug)) return badStore();
  const token = await currentToken(slug);
  const result = await callBackend(
    (client) => readCart({ client, path: { slug }, headers: tokenHeaders(token) }),
    { withSession: false }
  );
  return finish(slug, result);
}

/** Adds to the quantity already in the cart; starts a cart when the shopper has none. */
export async function addToCart(
  slug: string,
  variantId: string,
  quantity: number
): Promise<CartResult> {
  if (!isValidStoreSlug(slug)) return badStore();
  const token = await currentToken(slug);
  const result = await callBackend(
    (client) =>
      addCartItem({
        client,
        path: { slug },
        headers: tokenHeaders(token),
        body: { variant_id: variantId, quantity },
      }),
    { withSession: false }
  );
  return finish(slug, result, { token });
}

/** Sets the quantity of one variant (adds the line when it is not in the cart yet). */
export async function setCartQuantity(
  slug: string,
  variantId: string,
  quantity: number
): Promise<CartResult> {
  if (!isValidStoreSlug(slug)) return badStore();
  const token = await currentToken(slug);
  const result = await callBackend(
    (client) =>
      setCartItemQuantity({
        client,
        path: { slug, variant_id: variantId },
        headers: tokenHeaders(token),
        body: { quantity },
      }),
    { withSession: false }
  );
  return finish(slug, result, { token });
}

/** Removes one variant. Removing from a cart that does not exist creates nothing. */
export async function removeFromCart(slug: string, variantId: string): Promise<CartResult> {
  if (!isValidStoreSlug(slug)) return badStore();
  const token = await currentToken(slug);
  const result = await callBackend(
    (client) =>
      removeCartItem({
        client,
        path: { slug, variant_id: variantId },
        headers: tokenHeaders(token),
      }),
    { withSession: false }
  );
  return finish(slug, result, { token });
}
