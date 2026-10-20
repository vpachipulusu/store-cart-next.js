// @vitest-environment node
/** KAN-77: the checkout wrapper sends the store's cart token, builds return URLs on the store host and maps errors. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const jar = new Map<string, string>();
const cookieSet = vi.fn();
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({
    get: (name: string) => (jar.has(name) ? { value: jar.get(name) } : undefined),
    set: cookieSet,
  })),
  headers: vi.fn(async () => ({ get: () => null })),
}));

const log = vi.hoisted(() => ({ warn: vi.fn(), error: vi.fn() }));
vi.mock('@/lib/logger', () => ({ logger: log }));

import {
  CHECKOUT_CART_CHANGED_MESSAGE,
  CHECKOUT_FAILED_MESSAGE,
  CHECKOUT_INVALID_RETURN_MESSAGE,
  CHECKOUT_NOT_FOUND_MESSAGE,
  CHECKOUT_PAYMENTS_UNAVAILABLE_MESSAGE,
  CHECKOUT_RATE_LIMITED_MESSAGE,
  beginCheckout,
  checkoutErrorMessage,
} from '@/lib/api/checkout';

const TOKEN = 'T'.repeat(43);
const STRIPE_URL = 'https://checkout.stripe.com/c/pay/cs_test_1';
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const ok = (url: string) => json({ success: true, data: { order_id: 'o1', checkout_url: url } });

describe('beginCheckout', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

  beforeEach(() => {
    jar.clear();
    cookieSet.mockClear();
    log.warn.mockClear();
    log.error.mockClear();
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
    vi.stubEnv('BACKEND_INTERNAL_KEY', 'server-key');
    vi.stubEnv('PLATFORM_ROOT_DOMAIN', 'storecart.com');
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it('posts the store return URLs with this store token and no session, then returns the Stripe URL', async () => {
    jar.set('sc_cart_acme', TOKEN);
    jar.set('sc_cart_beta', 'B'.repeat(43));
    jar.set('session', 'merchant-session');
    fetchMock.mockResolvedValue(ok(STRIPE_URL));

    const result = await beginCheckout('acme');

    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe('POST');
    expect(request.url).toBe('http://backend.test/v1/storefront/acme/checkout');
    expect(request.headers.get('X-Cart-Token')).toBe(TOKEN);
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
    expect(request.headers.get('X-Session-Token')).toBeNull();
    expect(await request.json()).toEqual({
      success_url: 'https://acme.storecart.com/checkout/success',
      cancel_url: 'https://acme.storecart.com/checkout/cancel',
    });
    expect(result).toEqual({ success: true, data: { checkoutUrl: STRIPE_URL } });
    expect(cookieSet).not.toHaveBeenCalled();
  });

  it('sends no token header when the shopper has no cart (the backend answers 409)', async () => {
    fetchMock.mockResolvedValue(json({ success: false, error: 'x' }, 409));

    const result = await beginCheckout('acme');

    expect(fetchMock.mock.calls[0][0].headers.get('X-Cart-Token')).toBeNull();
    expect(result).toEqual({
      success: false,
      error: CHECKOUT_CART_CHANGED_MESSAGE,
      status: 409,
    });
  });

  it('ignores a malformed cookie value', async () => {
    jar.set('sc_cart_acme', 'not-a-token');
    fetchMock.mockResolvedValue(ok(STRIPE_URL));

    await beginCheckout('acme');

    expect(fetchMock.mock.calls[0][0].headers.get('X-Cart-Token')).toBeNull();
  });

  it('refuses an invalid slug without calling the backend', async () => {
    const result = await beginCheckout('../admin');

    expect(result).toMatchObject({ success: false, status: 404 });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ['http scheme', 'http://checkout.stripe.com/c/pay/x'],
    ['another host', 'https://evil.example/pay'],
    ['empty', ''],
    ['null', null],
    ['a number', 7],
  ])('does not return a checkout URL that is %s', async (_label, url) => {
    fetchMock.mockResolvedValue(
      json({ success: true, data: { order_id: 'o1', checkout_url: url } })
    );

    const result = await beginCheckout('acme');

    expect(result).toEqual({ success: false, error: CHECKOUT_FAILED_MESSAGE, status: 502 });
    expect(log.error).toHaveBeenCalledTimes(1);
  });

  it('uses the http store origin and port in development', async () => {
    vi.stubEnv('PLATFORM_ROOT_DOMAIN', 'localhost');
    vi.stubEnv('PORT', '3100');
    fetchMock.mockResolvedValue(ok(STRIPE_URL));

    await beginCheckout('acme');

    expect(await fetchMock.mock.calls[0][0].json()).toEqual({
      success_url: 'http://acme.localhost:3100/checkout/success',
      cancel_url: 'http://acme.localhost:3100/checkout/cancel',
    });
  });

  it('refuses to build localhost return URLs on a production deployment', async () => {
    vi.stubEnv('VERCEL_ENV', 'production');
    vi.stubEnv('PLATFORM_ROOT_DOMAIN', '');

    const result = await beginCheckout('acme');

    expect(result).toEqual({
      success: false,
      error: CHECKOUT_PAYMENTS_UNAVAILABLE_MESSAGE,
      status: 503,
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(log.error).toHaveBeenCalledTimes(1);
  });

  it('still starts checkout in production when the root domain is set', async () => {
    vi.stubEnv('VERCEL_ENV', 'production');
    fetchMock.mockResolvedValue(ok(STRIPE_URL));

    await expect(beginCheckout('acme')).resolves.toMatchObject({ success: true });
    expect(log.error).not.toHaveBeenCalled();
  });

  it('keeps the localhost default outside production (local development and e2e)', async () => {
    vi.stubEnv('PLATFORM_ROOT_DOMAIN', '');
    fetchMock.mockResolvedValue(ok(STRIPE_URL));

    await expect(beginCheckout('acme')).resolves.toMatchObject({ success: true });
  });

  it('logs the backend status for operators, never the cart token', async () => {
    jar.set('sc_cart_acme', TOKEN);
    fetchMock.mockResolvedValue(json({ success: false, error: 'boom' }, 502));

    await beginCheckout('acme');

    expect(log.warn).toHaveBeenCalledWith('Storefront checkout refused', {
      slug: 'acme',
      status: 502,
    });
    expect(JSON.stringify(log.warn.mock.calls)).not.toContain(TOKEN);
  });

  it.each([
    [404, CHECKOUT_NOT_FOUND_MESSAGE],
    [409, CHECKOUT_CART_CHANGED_MESSAGE],
    [422, CHECKOUT_INVALID_RETURN_MESSAGE],
    [429, CHECKOUT_RATE_LIMITED_MESSAGE],
    [502, CHECKOUT_PAYMENTS_UNAVAILABLE_MESSAGE],
    [503, CHECKOUT_PAYMENTS_UNAVAILABLE_MESSAGE],
    [500, CHECKOUT_FAILED_MESSAGE],
    [401, CHECKOUT_FAILED_MESSAGE],
    [400, CHECKOUT_FAILED_MESSAGE],
  ])('maps a backend %i to a fixed shopper message', async (status, message) => {
    fetchMock.mockResolvedValue(json({ success: false, error: 'stripe said: card_xyz' }, status));

    const result = await beginCheckout('acme');

    expect(result).toEqual({ success: false, error: message, status });
  });

  it('treats an unreachable backend as payments unavailable', async () => {
    fetchMock.mockRejectedValue(new Error('down'));

    const result = await beginCheckout('acme');

    expect(result).toMatchObject({ success: false, error: CHECKOUT_PAYMENTS_UNAVAILABLE_MESSAGE });
  });
});

describe('checkoutErrorMessage', () => {
  it('never echoes backend text', () => {
    expect(checkoutErrorMessage(409)).toBe(CHECKOUT_CART_CHANGED_MESSAGE);
    expect(checkoutErrorMessage(undefined)).toBe(CHECKOUT_PAYMENTS_UNAVAILABLE_MESSAGE);
    expect(checkoutErrorMessage(418)).toBe(CHECKOUT_FAILED_MESSAGE);
  });
});
