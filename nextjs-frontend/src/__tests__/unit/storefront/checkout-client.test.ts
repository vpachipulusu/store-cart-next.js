/** KAN-77: the browser call to this store's checkout route; it only accepts a Stripe-hosted URL back. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { startCheckout } from '@/lib/storefront/checkout-client';

const STRIPE_URL = 'https://checkout.stripe.com/c/pay/cs_test_1';
const FALLBACK = 'Checkout could not be started. Please try again.';
const fetchMock = vi.fn();

function reply(body: unknown, status = 200) {
  fetchMock.mockResolvedValue(new Response(JSON.stringify(body), { status }));
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe('startCheckout', () => {
  it('posts to the same-origin /checkout route and returns the URL', async () => {
    reply({ success: true, data: { checkoutUrl: STRIPE_URL } });

    await expect(startCheckout()).resolves.toEqual({ ok: true, url: STRIPE_URL });

    expect(fetchMock).toHaveBeenCalledWith('/checkout', { method: 'POST', cache: 'no-store' });
  });

  it('returns the shopper message of a failure', async () => {
    reply({ success: false, error: 'Too many requests.' }, 429);

    await expect(startCheckout()).resolves.toEqual({ ok: false, error: 'Too many requests.' });
  });

  it.each([
    [
      'a URL that is not Stripe-hosted',
      200,
      { success: true, data: { checkoutUrl: 'https://evil.example/pay' } },
    ],
    ['a missing URL', 200, { success: true, data: {} }],
    ['a non-string URL', 200, { success: true, data: { checkoutUrl: 42 } }],
    ['null data', 200, { success: true, data: null }],
    ['success false', 200, { success: false, data: { checkoutUrl: STRIPE_URL } }],
    ['a Stripe URL on a failed status', 502, { success: true, data: { checkoutUrl: STRIPE_URL } }],
    ['a null body', 200, null],
    ['an array body', 200, []],
    ['a non-string error', 500, { success: false, error: { code: 1 } }],
    ['an empty error', 500, { success: false, error: '' }],
  ])('never follows or trusts %s', async (_label, status, body) => {
    reply(body, status);

    await expect(startCheckout()).resolves.toEqual({ ok: false, error: FALLBACK });
  });

  it('returns a fallback when the call throws or the body is not JSON', async () => {
    fetchMock.mockRejectedValueOnce(new Error('offline'));
    await expect(startCheckout()).resolves.toEqual({ ok: false, error: FALLBACK });
    fetchMock.mockResolvedValueOnce(new Response('<html>', { status: 502 }));
    await expect(startCheckout()).resolves.toEqual({ ok: false, error: FALLBACK });
  });
});
