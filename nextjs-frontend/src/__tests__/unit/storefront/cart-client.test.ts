/** KAN-75: the theme's browser calls to the store's own cart route handlers. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  addToCart,
  CART_CHANGED_EVENT,
  itemCount,
  readCart,
  removeLine,
  setQuantity,
  type Cart,
} from '@/lib/storefront/cart-client';

const cart = {
  lines: [{ quantity: 2 }, { quantity: 3 }],
} as unknown as Cart;

function reply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

describe('cart client', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it('adds with a same-origin JSON POST and announces the change', async () => {
    fetchMock.mockResolvedValue(reply(200, { success: true, data: cart }));
    const heard = vi.fn();
    window.addEventListener(CART_CHANGED_EVENT, heard);

    const result = await addToCart('var1', 2);

    window.removeEventListener(CART_CHANGED_EVENT, heard);
    expect(result).toEqual({ ok: true, cart });
    expect(fetchMock).toHaveBeenCalledWith('/cart/items', {
      method: 'POST',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ variantId: 'var1', quantity: 2 }),
    });
    expect(heard).toHaveBeenCalledTimes(1);
  });

  it('reads without announcing a change', async () => {
    fetchMock.mockResolvedValue(reply(200, { success: true, data: cart }));
    const heard = vi.fn();
    window.addEventListener(CART_CHANGED_EVENT, heard);

    await readCart();

    window.removeEventListener(CART_CHANGED_EVENT, heard);
    expect(fetchMock.mock.calls[0][0]).toBe('/cart');
    expect(heard).not.toHaveBeenCalled();
  });

  it('encodes the variant id in line URLs', async () => {
    fetchMock.mockResolvedValue(reply(200, { success: true, data: cart }));

    await setQuantity('a/b', 3);
    await removeLine('a/b');

    expect(fetchMock.mock.calls.map((call) => [call[0], call[1].method])).toEqual([
      ['/cart/items/a%2Fb', 'PUT'],
      ['/cart/items/a%2Fb', 'DELETE'],
    ]);
  });

  it('shows the route error text, or a fixed one when there is none', async () => {
    fetchMock.mockResolvedValueOnce(reply(409, { success: false, error: 'Only 1 in stock' }));
    fetchMock.mockResolvedValueOnce(new Response('oops', { status: 502 }));
    fetchMock.mockRejectedValueOnce(new TypeError('offline'));

    expect(await addToCart('v', 5)).toEqual({ ok: false, error: 'Only 1 in stock' });
    expect((await addToCart('v', 1)).ok).toBe(false);
    expect(await readCart()).toEqual({
      ok: false,
      error: 'The basket could not be updated. Please try again.',
    });
  });

  it('counts items by quantity', () => {
    expect(itemCount(cart)).toBe(5);
  });
});
