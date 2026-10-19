// @vitest-environment node
/** KAN-76: the cart wrapper sends the store-scoped token, stores a newly issued one, and curates error messages. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const jar = new Map<string, string>();
const cookieSet = vi.fn((name: string, value: string) => void jar.set(name, value));
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({
    get: (name: string) => (jar.has(name) ? { value: jar.get(name) } : undefined),
    set: cookieSet,
  })),
  headers: vi.fn(async () => ({ get: () => null })),
}));

import {
  addToCart,
  CART_RATE_LIMITED_MESSAGE,
  CART_REQUEST_FAILED_MESSAGE,
  CART_UNAVAILABLE_MESSAGE,
  cartErrorMessage,
  fetchCart,
  removeFromCart,
  setCartQuantity,
} from '@/lib/api/cart';

const TOKEN = 'T'.repeat(43);
const NEW_TOKEN = 'N'.repeat(43);
const cartBody = (extra: Record<string, unknown> = {}) => ({
  success: true,
  data: {
    lines: [],
    subtotal_minor: 0,
    shipping_minor: 0,
    tax_minor: 0,
    total_minor: 0,
    prices_include_tax: false,
    can_checkout: false,
    ...extra,
  },
});
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('cart wrapper', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

  beforeEach(() => {
    jar.clear();
    cookieSet.mockClear();
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
    vi.stubEnv('BACKEND_INTERNAL_KEY', 'server-key');
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it('sends the token of this store and no session', async () => {
    jar.set('sc_cart_acme', TOKEN);
    jar.set('session', 'merchant-session');
    fetchMock.mockResolvedValue(json(cartBody()));

    const result = await fetchCart('acme');

    const request = fetchMock.mock.calls[0][0];
    expect(request.url).toBe('http://backend.test/v1/storefront/acme/cart');
    expect(request.headers.get('X-Cart-Token')).toBe(TOKEN);
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
    expect(request.headers.get('X-Session-Token')).toBeNull();
    expect(result.success).toBe(true);
  });

  it('does not send the token of another store', async () => {
    jar.set('sc_cart_beta', TOKEN);
    fetchMock.mockResolvedValue(json(cartBody()));

    await fetchCart('acme');

    expect(fetchMock.mock.calls[0][0].headers.get('X-Cart-Token')).toBeNull();
  });

  it('ignores a malformed cookie value', async () => {
    jar.set('sc_cart_acme', 'not-a-token');
    fetchMock.mockResolvedValue(json(cartBody()));

    await fetchCart('acme');

    expect(fetchMock.mock.calls[0][0].headers.get('X-Cart-Token')).toBeNull();
  });

  it('stores a newly issued token in the cookie and never returns it', async () => {
    fetchMock.mockResolvedValue(json(cartBody({ cart_token: NEW_TOKEN })));

    const result = await addToCart('acme', 'v1', 2);

    expect(cookieSet).toHaveBeenCalledWith(
      'sc_cart_acme',
      NEW_TOKEN,
      expect.objectContaining({ httpOnly: true, sameSite: 'lax' })
    );
    expect(result.success).toBe(true);
    if (result.success) expect(result.data).not.toHaveProperty('cart_token');
    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe('POST');
    expect(await request.json()).toEqual({ variant_id: 'v1', quantity: 2 });
  });

  it('re-sets the cookie with the same token after a write, so its lifetime slides', async () => {
    jar.set('sc_cart_acme', TOKEN);
    fetchMock.mockResolvedValue(json(cartBody()));

    await setCartQuantity('acme', 'v1', 3);

    expect(cookieSet).toHaveBeenCalledWith(
      'sc_cart_acme',
      TOKEN,
      expect.objectContaining({ maxAge: 2_592_000, httpOnly: true })
    );
    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe('PUT');
    expect(request.url).toBe('http://backend.test/v1/storefront/acme/cart/items/v1');
  });

  it('never sets the cookie on a read', async () => {
    jar.set('sc_cart_acme', TOKEN);
    fetchMock.mockResolvedValue(json(cartBody()));

    await fetchCart('acme');

    expect(cookieSet).not.toHaveBeenCalled();
  });

  it('does not set a cookie after a failed write', async () => {
    jar.set('sc_cart_acme', TOKEN);
    fetchMock.mockResolvedValue(json({ success: false, error: 'Only 3 in stock' }, 409));

    await addToCart('acme', 'v1', 9);

    expect(cookieSet).not.toHaveBeenCalled();
  });

  it('removes a line with DELETE', async () => {
    fetchMock.mockResolvedValue(json(cartBody()));

    await removeFromCart('acme', 'v1');

    expect(fetchMock.mock.calls[0][0].method).toBe('DELETE');
  });

  it('never calls the backend for an invalid store slug', async () => {
    const result = await fetchCart('Bad_Slug');

    expect(result).toMatchObject({ success: false, status: 404 });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('shows the backend message for a stock conflict', async () => {
    fetchMock.mockResolvedValue(json({ success: false, error: 'Only 3 in stock' }, 409));

    expect(await addToCart('acme', 'v1', 9)).toEqual({
      success: false,
      error: 'Only 3 in stock',
      status: 409,
    });
  });

  it('hides backend text for other failures', () => {
    expect(cartErrorMessage({ error: 'boom: secret', status: 500 })).toBe(
      CART_REQUEST_FAILED_MESSAGE
    );
    expect(cartErrorMessage({ error: 'x', status: 429 })).toBe(CART_RATE_LIMITED_MESSAGE);
    expect(cartErrorMessage({ error: 'x', status: 503 })).toBe(CART_UNAVAILABLE_MESSAGE);
    expect(cartErrorMessage({ error: 'x' })).toBe(CART_UNAVAILABLE_MESSAGE);
    expect(cartErrorMessage({ error: 'Request failed', status: 409 })).toBe(
      CART_REQUEST_FAILED_MESSAGE
    );
  });
});
