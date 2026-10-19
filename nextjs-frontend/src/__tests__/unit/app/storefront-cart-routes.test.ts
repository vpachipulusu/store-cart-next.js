// @vitest-environment node
/** KAN-76: the cart route handlers need the proxy's slug header, refuse cross-site writes and validate bodies. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const headerGet = vi.fn();
vi.mock('next/headers', () => ({ headers: vi.fn(async () => ({ get: headerGet })) }));

const api = vi.hoisted(() => ({
  fetchCart: vi.fn(),
  addToCart: vi.fn(),
  setCartQuantity: vi.fn(),
  removeFromCart: vi.fn(),
}));
vi.mock('@/lib/api/cart', () => api);

import { GET } from '@/app/storefront/[slug]/cart/route';
import { POST } from '@/app/storefront/[slug]/cart/items/route';
import { DELETE, PUT } from '@/app/storefront/[slug]/cart/items/[variantId]/route';

const EMPTY = { lines: [], subtotal_minor: 0, total_minor: 0, can_checkout: false };
const ok = { success: true, data: EMPTY };
const slugParams = { params: Promise.resolve({ slug: 'acme' }) };
const lineParams = { params: Promise.resolve({ slug: 'acme', variantId: 'v1' }) };

function write(method: string, body?: unknown, headers: Record<string, string> = {}): Request {
  return new Request('http://acme.localhost:3000/cart/items', {
    method,
    headers: { 'content-type': 'application/json', host: 'acme.localhost:3000', ...headers },
    body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body),
  });
}

describe('storefront cart routes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    headerGet.mockReturnValue('acme');
    for (const fn of Object.values(api)) fn.mockResolvedValue(ok);
  });

  it('returns the cart uncached', async () => {
    const response = await GET(new Request('http://x/cart'), slugParams);

    expect(response.status).toBe(200);
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    expect(await response.json()).toEqual({ success: true, data: EMPTY });
    expect(api.fetchCart).toHaveBeenCalledWith('acme');
  });

  it('is a 404 unless the proxy rewrote to this same slug', async () => {
    headerGet.mockReturnValue(null);
    expect((await GET(new Request('http://x/cart'), slugParams)).status).toBe(404);
    headerGet.mockReturnValue('other');
    expect((await POST(write('POST', { variantId: 'v1', quantity: 1 }), slugParams)).status).toBe(
      404
    );
    expect(api.fetchCart).not.toHaveBeenCalled();
    expect(api.addToCart).not.toHaveBeenCalled();
  });

  it('adds an item', async () => {
    const response = await POST(write('POST', { variantId: 'v1', quantity: 2 }), slugParams);

    expect(response.status).toBe(200);
    expect(api.addToCart).toHaveBeenCalledWith('acme', 'v1', 2);
  });

  it.each([
    { variantId: 'v1', quantity: 0 },
    { variantId: 'v1', quantity: 100 },
    { variantId: 'v1', quantity: 1.5 },
    { variantId: 'v1', quantity: '2' },
    { variantId: '', quantity: 1 },
    { quantity: 1 },
    'not json',
  ])('rejects the body %j before calling the backend', async (body) => {
    const response = await POST(write('POST', body), slugParams);

    expect(response.status).toBe(422);
    expect(api.addToCart).not.toHaveBeenCalled();
  });

  it('refuses a body that is not JSON', async () => {
    const response = await POST(
      write('POST', '{"variantId":"v1","quantity":1}', { 'content-type': 'text/plain' }),
      slugParams
    );

    expect(response.status).toBe(415);
  });

  it('refuses a write from another origin but allows the same origin and no origin', async () => {
    const body = { variantId: 'v1', quantity: 1 };

    const foreign = await POST(write('POST', body, { origin: 'https://evil.example' }), slugParams);
    const same = await POST(
      write('POST', body, { origin: 'http://acme.localhost:3000' }),
      slugParams
    );
    const none = await POST(write('POST', body), slugParams);

    expect(foreign.status).toBe(403);
    expect(same.status).toBe(200);
    expect(none.status).toBe(200);
    expect(api.addToCart).toHaveBeenCalledTimes(2);
  });

  it('refuses an Origin of null', async () => {
    const response = await POST(
      write('POST', { variantId: 'v1', quantity: 1 }, { origin: 'null' }),
      slugParams
    );

    expect(response.status).toBe(403);
    expect(api.addToCart).not.toHaveBeenCalled();
  });

  it('refuses a body that is too large, by declared length or by content', async () => {
    const declared = await POST(
      write('POST', { variantId: 'v1', quantity: 1 }, { 'content-length': '5000' }),
      slugParams
    );
    const actual = await POST(
      write('POST', JSON.stringify({ variantId: 'v1', quantity: 1, pad: 'x'.repeat(3000) })),
      slugParams
    );

    expect(declared.status).toBe(413);
    expect(actual.status).toBe(413);
    expect(api.addToCart).not.toHaveBeenCalled();
  });

  it.each(['..', 'a.b', 'a/b', '%2E%2E', 'x'.repeat(101)])(
    'rejects the variant id %j on PUT and DELETE',
    async (variantId) => {
      const params = { params: Promise.resolve({ slug: 'acme', variantId }) };

      const put = await PUT(write('PUT', { quantity: 1 }), params);
      const del = await DELETE(write('DELETE'), params);

      expect(put.status).toBe(422);
      expect(del.status).toBe(422);
      expect(api.setCartQuantity).not.toHaveBeenCalled();
      expect(api.removeFromCart).not.toHaveBeenCalled();
    }
  );

  it('passes a rate limit through', async () => {
    api.fetchCart.mockResolvedValue({ success: false, error: 'Too many requests', status: 429 });

    expect((await GET(new Request('http://x/cart'), slugParams)).status).toBe(429);
  });

  it('sets a line quantity and removes a line', async () => {
    const put = await PUT(write('PUT', { quantity: 4 }), lineParams);
    const del = await DELETE(write('DELETE'), lineParams);

    expect(put.status).toBe(200);
    expect(del.status).toBe(200);
    expect(api.setCartQuantity).toHaveBeenCalledWith('acme', 'v1', 4);
    expect(api.removeFromCart).toHaveBeenCalledWith('acme', 'v1');
  });

  it('passes a stock conflict through with its message', async () => {
    api.addToCart.mockResolvedValue({ success: false, error: 'Only 3 in stock', status: 409 });

    const response = await POST(write('POST', { variantId: 'v1', quantity: 9 }), slugParams);

    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ success: false, error: 'Only 3 in stock' });
  });

  it('maps an unreachable or unexpected backend to 503 or 502', async () => {
    api.fetchCart.mockResolvedValueOnce({ success: false, error: 'down' });
    expect((await GET(new Request('http://x/cart'), slugParams)).status).toBe(503);
    api.fetchCart.mockResolvedValueOnce({ success: false, error: 'bad', status: 500 });
    expect((await GET(new Request('http://x/cart'), slugParams)).status).toBe(502);
  });
});
