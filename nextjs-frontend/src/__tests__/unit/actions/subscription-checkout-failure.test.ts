// @vitest-environment node
/**
 * KAN-250: starting checkout must name the failure cause (status class, never secrets) in the server log and give
 * the pricing page a specific, curated message instead of one generic string. Billing API and auth are mocked.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const NO_ORG = 'No organisation you can manage billing for was found';

const mocks = vi.hoisted(() => ({
  startBillingCheckout: vi.fn(),
  getVerifiedUserId: vi.fn(),
  buildCheckoutReturnUrls: vi.fn(),
  cookieSet: vi.fn(),
  loggerError: vi.fn(),
}));

vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: vi.fn(), set: mocks.cookieSet, delete: vi.fn() })),
}));
vi.mock('@/lib/auth/verified-session', () => ({ getVerifiedUserId: mocks.getVerifiedUserId }));
vi.mock('@/lib/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: mocks.loggerError },
}));
vi.mock('@/lib/stripe/return-urls', () => ({
  buildCheckoutReturnUrls: mocks.buildCheckoutReturnUrls,
  buildBillingPortalReturnUrl: vi.fn(),
}));
vi.mock('@/lib/api/billing', () => ({
  NO_BILLING_ORGANIZATION_MESSAGE: 'No organisation you can manage billing for was found',
  startBillingCheckout: mocks.startBillingCheckout,
  fetchBillingSummary: vi.fn(),
  fetchBillingInvoices: vi.fn(),
  fetchBillingPaymentMethods: vi.fn(),
  startBillingPortal: vi.fn(),
  changeBillingPlan: vi.fn(),
  cancelBillingSubscription: vi.fn(),
  resumeBillingSubscription: vi.fn(),
  deleteBillingPaymentMethod: vi.fn(),
  setDefaultBillingPaymentMethod: vi.fn(),
}));

import { createCheckoutSessionAction } from '@/app/actions/subscription-actions';

const URLS = {
  successUrl: 'https://app.test/dashboard?upgrade=success',
  cancelUrl: 'https://app.test/pricing',
};

describe('createCheckoutSessionAction failure causes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getVerifiedUserId.mockResolvedValue('user-1');
    mocks.buildCheckoutReturnUrls.mockReturnValue(URLS);
  });

  it.each(['monthly', 'yearly'] as const)('returns the Stripe url for Pro %s', async (period) => {
    mocks.startBillingCheckout.mockResolvedValue({
      success: true,
      data: { url: 'https://checkout.stripe.com/c/pay/cs_test' },
    });

    const result = await createCheckoutSessionAction('pro', period);

    expect(mocks.startBillingCheckout).toHaveBeenCalledWith(
      'pro',
      period,
      URLS.successUrl,
      URLS.cancelUrl
    );
    expect(result).toEqual({
      success: true,
      data: { url: 'https://checkout.stripe.com/c/pay/cs_test' },
    });
    expect(mocks.cookieSet).toHaveBeenCalledWith(
      'checkout_token',
      expect.any(String),
      expect.any(Object)
    );
  });

  it.each([
    [{ error: NO_ORG }, 'no_organization', /create a store/i],
    [{ error: 'Invalid return URL', status: 422 }, 'invalid_return_url', /try again later/i],
    [
      { error: 'Service temporarily unavailable', status: 503 },
      'not_configured',
      /try again later/i,
    ],
    [
      { error: 'Billing provider unavailable', status: 502 },
      'provider_unavailable',
      /payment provider/i,
    ],
    [
      { error: 'Operation not allowed in the current state', status: 409 },
      'not_allowed',
      /already/i,
    ],
    [{ error: 'Forbidden', status: 403 }, 'forbidden', /owner or admin/i],
    [{ error: 'Invalid authentication', status: 401 }, 'session_expired', /sign in again/i],
    [{ error: 'Organization not found', status: 404 }, 'forbidden', /owner or admin/i],
    [{ error: 'Backend unavailable' }, 'backend_unavailable', /reach the billing service/i],
    [{ error: 'Request failed', status: 500 }, 'unknown', /could not start checkout/i],
  ])('maps %j to %s with a curated message and a cause log', async (failure, code, message) => {
    mocks.startBillingCheckout.mockResolvedValue({ success: false, ...failure });

    const result = await createCheckoutSessionAction('pro', 'monthly');

    expect(result).toMatchObject({ success: false, code });
    expect(result.error).toMatch(message);
    expect(result.error).not.toContain((failure as { error: string }).error);
    expect(mocks.loggerError).toHaveBeenCalledWith(
      'Create checkout session failed:',
      expect.objectContaining({ code, status: (failure as { status?: number }).status })
    );
    expect(mocks.cookieSet).not.toHaveBeenCalled();
  });

  it('passes the enterprise plan through and classifies its failures the same way', async () => {
    mocks.startBillingCheckout.mockResolvedValue({ success: false, error: 'x', status: 502 });

    const result = await createCheckoutSessionAction('enterprise', 'yearly');

    expect(mocks.startBillingCheckout.mock.calls[0].slice(0, 2)).toEqual(['enterprise', 'yearly']);
    expect(result).toMatchObject({ success: false, code: 'provider_unavailable' });
  });

  it('reports a missing return-url setting with its own code', async () => {
    mocks.buildCheckoutReturnUrls.mockImplementation(() => {
      throw new Error('NEXT_PUBLIC_APP_URL must be set in production to build Stripe return URLs.');
    });

    const result = await createCheckoutSessionAction('pro', 'yearly');

    expect(result).toMatchObject({ success: false, code: 'return_url_config' });
    expect(mocks.startBillingCheckout).not.toHaveBeenCalled();
    expect(mocks.loggerError).toHaveBeenCalledWith(
      'Create checkout session failed:',
      expect.objectContaining({ code: 'return_url_config', cause: 'Error' })
    );
  });

  it('keeps the generic message and logs the original error when the billing wrapper throws', async () => {
    const boom = new TypeError('boom');
    mocks.startBillingCheckout.mockRejectedValue(boom);

    const result = await createCheckoutSessionAction('pro', 'monthly');

    expect(result).toEqual({ success: false, error: 'Failed to create checkout session' });
    expect(mocks.loggerError).toHaveBeenCalledWith('Create checkout session error:', boom);
  });

  it('keeps unauthenticated callers out without calling the API', async () => {
    mocks.getVerifiedUserId.mockResolvedValue(null);

    const result = await createCheckoutSessionAction('pro', 'monthly');

    expect(result).toEqual({ success: false, error: 'Unauthorized' });
    expect(mocks.startBillingCheckout).not.toHaveBeenCalled();
  });
});
