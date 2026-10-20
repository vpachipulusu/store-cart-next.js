// @vitest-environment node
/** KAN-77: the checkout route handler needs the proxy's slug header, refuses cross-site posts and never caches. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const headerGet = vi.fn();
vi.mock('next/headers', () => ({ headers: vi.fn(async () => ({ get: headerGet })) }));

const api = vi.hoisted(() => ({ beginCheckout: vi.fn() }));
vi.mock('@/lib/api/checkout', () => api);

import { POST } from '@/app/storefront/[slug]/checkout/route';

const STRIPE_URL = 'https://checkout.stripe.com/c/pay/cs_test_1';
const slugParams = { params: Promise.resolve({ slug: 'acme' }) };

function post(headers: Record<string, string> = {}): Request {
  return new Request('http://acme.localhost:3000/checkout', {
    method: 'POST',
    headers: { host: 'acme.localhost:3000', ...headers },
  });
}

describe('storefront checkout route', () => {
  it('exports POST only', async () => {
    const routeModule = await import('@/app/storefront/[slug]/checkout/route');

    expect(Object.keys(routeModule).filter((key) => /^(GET|PUT|PATCH|DELETE)$/.test(key))).toEqual(
      []
    );
    expect(typeof routeModule.POST).toBe('function');
  });

  beforeEach(() => {
    vi.clearAllMocks();
    headerGet.mockReturnValue('acme');
    api.beginCheckout.mockResolvedValue({ success: true, data: { checkoutUrl: STRIPE_URL } });
  });

  it('returns the Stripe URL uncached', async () => {
    const response = await POST(post({ origin: 'http://acme.localhost:3000' }), slugParams);

    expect(response.status).toBe(200);
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    expect(await response.json()).toEqual({ success: true, data: { checkoutUrl: STRIPE_URL } });
    expect(api.beginCheckout).toHaveBeenCalledWith('acme');
  });

  it('is a 404 unless the proxy rewrote to this same slug', async () => {
    headerGet.mockReturnValue('other');

    expect((await POST(post(), slugParams)).status).toBe(404);
    expect(api.beginCheckout).not.toHaveBeenCalled();
  });

  it('refuses a post from another host, including a sibling store', async () => {
    const response = await POST(post({ origin: 'http://evil.localhost:3000' }), slugParams);

    expect(response.status).toBe(403);
    expect(api.beginCheckout).not.toHaveBeenCalled();
  });

  it.each([404, 409, 422, 429, 502, 503])('passes a %i with its message', async (status) => {
    api.beginCheckout.mockResolvedValue({ success: false, error: 'Shopper message', status });

    const response = await POST(post(), slugParams);

    expect(response.status).toBe(status);
    expect(await response.json()).toEqual({ success: false, error: 'Shopper message' });
  });

  it('turns an unknown status into 502 and a missing one into 503', async () => {
    api.beginCheckout.mockResolvedValueOnce({ success: false, error: 'x', status: 500 });
    expect((await POST(post(), slugParams)).status).toBe(502);
    api.beginCheckout.mockResolvedValueOnce({ success: false, error: 'x' });
    expect((await POST(post(), slugParams)).status).toBe(503);
  });
});
