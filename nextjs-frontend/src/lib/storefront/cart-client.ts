import type { Cart } from '@/lib/api/cart';

/**
 * Browser calls to this store's own cart route handlers (KAN-76) for the storefront theme (KAN-75). Same-origin
 * relative URLs only: the page is on the store host, so the httpOnly cart cookie and `Origin` go with them. The
 * browser never calls the backend.
 */

export type { Cart };

export type CartReply = { ok: true; cart: Cart } | { ok: false; error: string };

/** Fired on `window` after any cart change, so the header count can refresh. */
export const CART_CHANGED_EVENT = 'storefront:cart-changed';

const FALLBACK_ERROR = 'The basket could not be updated. Please try again.';

/** The minimum the theme reads; anything else is treated as a failed call. */
function isCart(value: unknown): value is Cart {
  if (typeof value !== 'object' || value === null) return false;
  const cart = value as { lines?: unknown; total_minor?: unknown };
  return (
    Array.isArray(cart.lines) &&
    cart.lines.every(
      (line: unknown) =>
        typeof line === 'object' &&
        line !== null &&
        typeof (line as { quantity?: unknown }).quantity === 'number'
    ) &&
    typeof cart.total_minor === 'number'
  );
}

async function send(method: string, path: string, body?: unknown): Promise<CartReply> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      cache: 'no-store',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    return { ok: false, error: FALLBACK_ERROR };
  }
  let parsed: unknown = null;
  try {
    parsed = await response.json();
  } catch {
    parsed = null;
  }
  const reply = parsed as { success?: boolean; data?: unknown; error?: unknown } | null;
  if (response.ok && reply?.success && isCart(reply.data)) {
    if (method !== 'GET' && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent(CART_CHANGED_EVENT, { detail: reply.data }));
    }
    return { ok: true, cart: reply.data };
  }
  return { ok: false, error: typeof reply?.error === 'string' ? reply.error : FALLBACK_ERROR };
}

export function readCart(): Promise<CartReply> {
  return send('GET', '/cart');
}

export function addToCart(variantId: string, quantity: number): Promise<CartReply> {
  return send('POST', '/cart/items', { variantId, quantity });
}

export function setQuantity(variantId: string, quantity: number): Promise<CartReply> {
  return send('PUT', `/cart/items/${encodeURIComponent(variantId)}`, { quantity });
}

export function removeLine(variantId: string): Promise<CartReply> {
  return send('DELETE', `/cart/items/${encodeURIComponent(variantId)}`);
}

/** Items in the cart, counting quantities. */
export function itemCount(cart: Cart): number {
  return cart.lines.reduce((sum, line) => sum + line.quantity, 0);
}
