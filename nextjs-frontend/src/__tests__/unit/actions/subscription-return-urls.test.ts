// @vitest-environment node
/**
 * KAN-127: checkout success/cancel URLs and the billing-portal return URL are built on the server from the app's own
 * origin. Nothing a client sends may reach Stripe. Stripe, the database and auth are mocked; no real keys are used.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const APP_ORIGIN = 'https://shop.example.test';

const mocks = vi.hoisted(() => ({
  checkoutCreate: vi.fn(),
  portalCreate: vi.fn(),
  customersCreate: vi.fn(),
  userFindUnique: vi.fn(),
  userUpdate: vi.fn(),
  cookieSet: vi.fn(),
}));

vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ set: mocks.cookieSet, get: vi.fn() })),
  headers: vi.fn(),
}));
vi.mock('@/lib/auth/verified-session', () => ({ getVerifiedUserId: vi.fn(async () => 'user-1') }));
vi.mock('@/lib/logger', () => ({ logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/db/client', () => ({
  db: { user: { findUnique: mocks.userFindUnique, update: mocks.userUpdate } },
}));
vi.mock('@/lib/stripe/server', () => ({
  getStripeServerClient: () => ({
    checkout: { sessions: { create: mocks.checkoutCreate } },
    billingPortal: { sessions: { create: mocks.portalCreate } },
    customers: { create: mocks.customersCreate },
  }),
}));

const HOSTILE_URLS = [
  'https://evil.example',
  'https://evil.example/phish',
  '//evil.example',
  '/\\evil.example',
  '\\\\evil.example',
  'https:\\\\evil.example',
  'javascript:alert(1)',
  'data:text/html,<script>alert(1)</script>',
  'https://shop.example.test.evil.example',
  'https://shop.example.test@evil.example',
];

async function loadActions() {
  return import('@/app/actions/subscription-actions');
}

describe('KAN-127: Stripe return URLs are server-built', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    vi.stubEnv('NEXT_PUBLIC_APP_URL', APP_ORIGIN);
    vi.stubEnv('STRIPE_PRICE_ID_PRO_MONTHLY', 'price_test_pro_monthly');
    mocks.userFindUnique.mockResolvedValue({
      id: 'user-1',
      email: 'u@example.test',
      firebaseUid: 'fb-1',
      stripeCustomerId: 'cus_test_1',
    });
    mocks.checkoutCreate.mockResolvedValue({
      id: 'cs_test_1',
      url: 'https://checkout.stripe.test/s',
    });
    mocks.portalCreate.mockResolvedValue({ url: 'https://billing.stripe.test/p' });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('uses fixed same-origin success and cancel URLs for checkout', async () => {
    const { createCheckoutSessionAction } = await loadActions();

    const result = await createCheckoutSessionAction('pro', 'monthly');

    expect(result.error).toBeUndefined();
    expect(result.success).toBe(true);
    expect(mocks.checkoutCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        success_url: `${APP_ORIGIN}/dashboard?upgrade=success`,
        cancel_url: `${APP_ORIGIN}/pricing?upgrade=cancelled`,
      })
    );
  });

  it('uses a fixed same-origin return URL for the billing portal', async () => {
    const { createBillingPortalSessionAction } = await loadActions();

    const result = await createBillingPortalSessionAction();

    expect(result.success).toBe(true);
    expect(mocks.portalCreate).toHaveBeenCalledWith({
      customer: 'cus_test_1',
      return_url: `${APP_ORIGIN}/dashboard/settings/billing`,
    });
  });

  it('strips any path from the configured origin', async () => {
    vi.stubEnv('NEXT_PUBLIC_APP_URL', `${APP_ORIGIN}/some/path?x=1`);
    const { createBillingPortalSessionAction } = await loadActions();

    await createBillingPortalSessionAction();

    expect(mocks.portalCreate.mock.calls[0][0].return_url).toBe(
      `${APP_ORIGIN}/dashboard/settings/billing`
    );
  });

  it('falls back to the site config origin when NEXT_PUBLIC_APP_URL is unset', async () => {
    vi.stubEnv('NEXT_PUBLIC_APP_URL', '');
    const { createBillingPortalSessionAction } = await loadActions();

    await createBillingPortalSessionAction();

    expect(mocks.portalCreate.mock.calls[0][0].return_url).toBe(
      'http://localhost:3000/dashboard/settings/billing'
    );
  });

  describe('origin resolution by environment', () => {
    it('throws in production when NEXT_PUBLIC_APP_URL is unset', async () => {
      vi.stubEnv('NODE_ENV', 'production');
      vi.stubEnv('VERCEL_ENV', 'production');
      vi.stubEnv('NEXT_PUBLIC_APP_URL', '');
      const { buildBillingPortalReturnUrl } = await import('@/lib/stripe/return-urls');

      expect(() => buildBillingPortalReturnUrl()).toThrow(/NEXT_PUBLIC_APP_URL must be set/);
    });

    it('throws in production when NEXT_PUBLIC_APP_URL is malformed', async () => {
      vi.stubEnv('NODE_ENV', 'production');
      vi.stubEnv('NEXT_PUBLIC_APP_URL', 'not a url');
      const { buildCheckoutReturnUrls } = await import('@/lib/stripe/return-urls');

      expect(() => buildCheckoutReturnUrls()).toThrow(/not a valid URL/);
    });

    it('uses VERCEL_URL on a preview deployment when NEXT_PUBLIC_APP_URL is unset', async () => {
      vi.stubEnv('NODE_ENV', 'production');
      vi.stubEnv('VERCEL_ENV', 'preview');
      vi.stubEnv('VERCEL_URL', 'storecart-git-x.vercel.app');
      vi.stubEnv('NEXT_PUBLIC_APP_URL', '');
      const { buildBillingPortalReturnUrl } = await import('@/lib/stripe/return-urls');

      expect(buildBillingPortalReturnUrl()).toBe(
        'https://storecart-git-x.vercel.app/dashboard/settings/billing'
      );
    });

    it('defaults to localhost locally when nothing is set', async () => {
      vi.stubEnv('NODE_ENV', 'development');
      vi.stubEnv('VERCEL_URL', '');
      vi.stubEnv('NEXT_PUBLIC_APP_URL', '');
      const { buildBillingPortalReturnUrl } = await import('@/lib/stripe/return-urls');

      expect(buildBillingPortalReturnUrl()).toBe(
        'http://localhost:3000/dashboard/settings/billing'
      );
    });
  });

  describe.each(HOSTILE_URLS)('hostile client input %s', (hostile) => {
    it('never reaches Stripe for checkout, even if extra arguments are smuggled in', async () => {
      const { createCheckoutSessionAction } = await loadActions();
      const smuggled = createCheckoutSessionAction as unknown as (
        ...args: unknown[]
      ) => Promise<unknown>;

      await smuggled('pro', 'monthly', hostile, hostile);

      const params = mocks.checkoutCreate.mock.calls[0][0];
      expect(params.success_url).toBe(`${APP_ORIGIN}/dashboard?upgrade=success`);
      expect(params.cancel_url).toBe(`${APP_ORIGIN}/pricing?upgrade=cancelled`);
      expect(JSON.stringify(params)).not.toContain('evil.example');
      expect(JSON.stringify(params)).not.toContain('javascript:');
    });

    it('never reaches Stripe for the billing portal, even if an extra argument is smuggled in', async () => {
      const { createBillingPortalSessionAction } = await loadActions();
      const smuggled = createBillingPortalSessionAction as unknown as (
        ...args: unknown[]
      ) => Promise<unknown>;

      await smuggled(hostile);

      const params = mocks.portalCreate.mock.calls[0][0];
      expect(params.return_url).toBe(`${APP_ORIGIN}/dashboard/settings/billing`);
      expect(JSON.stringify(params)).not.toContain('evil.example');
      expect(JSON.stringify(params)).not.toContain('javascript:');
    });
  });
});
