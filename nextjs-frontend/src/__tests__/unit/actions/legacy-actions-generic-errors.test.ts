// @vitest-environment node
/**
 * KAN-172: the legacy subscription server actions must never return raw
 * Stripe/Firebase error text to the client. Every dependency is mocked to reject with a
 * secret-looking error; each action must answer with its stable generic message, leak nothing, and
 * hand the original error (with a message string) to the logger.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Secret-looking fragments are assembled at runtime so secret scanners do not flag this file.
const STRIPE_KEY = ['sk', 'live', '51HxYzSECRETKEY0123456789'].join('_');
const JWT = ['eyJhbGciOiJIUzI1NiJ9', 'eyJzdWIiOiIxIn0', 'c2lnbmF0dXJl'].join('.');
const DB_URL = ['postgres:', '', 'dbuser:dbpass@internal-host:5432/storecart'].join('/');
const EMAIL = 'victim.person@example.com';
const LEAK_FRAGMENTS = [STRIPE_KEY, JWT, DB_URL, EMAIL, 'dbpass', 'internal-host', 'SECRET-LEAK'];

const SECRET_ERROR = new Error(
  `SECRET-LEAK Invalid API Key ${STRIPE_KEY} for ${EMAIL} token=${JWT} at ${DB_URL}`
);

const mocks = vi.hoisted(() => {
  const state = { error: undefined as unknown };
  const fail = () => Promise.reject(state.error);

  // Any property access yields another proxy; calling any of them rejects with the secret error.
  const deepRejecting = (): any =>
    new Proxy(function () {}, {
      get: (_t, prop) => (prop === 'then' ? undefined : deepRejecting()),
      apply: () => fail(),
    });

  return {
    state,
    deepRejecting,
    logError: vi.fn(),
    verifySession: vi.fn(),
    getVerifiedUserId: vi.fn(),
  };
});

vi.mock('next/headers', () => ({
  cookies: async () => ({
    get: () => ({ value: 'session-cookie' }),
    set: () => {
      throw mocks.state.error;
    },
    delete: () => {
      throw mocks.state.error;
    },
  }),
}));
// The subscription actions reach Stripe and the database only through the billing API wrapper (KAN-45).
vi.mock('@/lib/api/billing', () => {
  const reject = () => Promise.reject(mocks.state.error);
  return {
    NO_BILLING_ORGANIZATION_MESSAGE: 'No organisation you can manage billing for was found',
    fetchBillingSummary: reject,
    fetchBillingInvoices: reject,
    fetchBillingPaymentMethods: reject,
    startBillingCheckout: reject,
    startBillingPortal: reject,
    changeBillingPlan: reject,
    cancelBillingSubscription: reject,
    resumeBillingSubscription: reject,
    deleteBillingPaymentMethod: reject,
    setDefaultBillingPaymentMethod: reject,
  };
});
vi.mock('next/cache', () => ({ revalidatePath: vi.fn(), revalidateTag: vi.fn() }));
vi.mock('@/lib/stripe/server', () => ({ getStripeServerClient: () => mocks.deepRejecting() }));
vi.mock('@/lib/firebase/admin', () => ({ getAdminAuth: () => mocks.deepRejecting() }));
vi.mock('@/lib/auth/verified-session', () => ({
  getVerifiedUserId: mocks.getVerifiedUserId,
  verifyVerifiedSessionCookie: mocks.verifySession,
}));
vi.mock('@/lib/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: mocks.logError },
}));

import * as subscription from '@/app/actions/subscription-actions';

type Result = { success: boolean; error?: string; data?: unknown };
type Row = [name: string, call: () => Promise<Result>, generic: string];

const ROWS: Row[] = [
  // subscription-actions.ts (12; the upcoming invoice has no API and stays removed)
  [
    'getSubscriptionStatusAction',
    () => subscription.getSubscriptionStatusAction(),
    'Failed to get subscription status',
  ],
  [
    'createCheckoutSessionAction',
    () => subscription.createCheckoutSessionAction('pro', 'monthly'),
    'Failed to create checkout session',
  ],
  [
    'verifyUpgradeSessionAction',
    () => subscription.verifyUpgradeSessionAction() as Promise<Result>,
    'Failed to verify upgrade session',
  ],
  [
    'createBillingPortalSessionAction',
    () => subscription.createBillingPortalSessionAction(),
    'Failed to create billing portal session',
  ],
  [
    'cancelSubscriptionAction',
    () => subscription.cancelSubscriptionAction(),
    'Failed to cancel subscription',
  ],
  [
    'resumeSubscriptionAction',
    () => subscription.resumeSubscriptionAction(),
    'Failed to resume subscription',
  ],
  [
    'updateSubscriptionAction',
    () => subscription.updateSubscriptionAction('pro', 'monthly'),
    'Failed to update subscription',
  ],
  [
    'getSubscriptionInvoicesAction',
    () => subscription.getSubscriptionInvoicesAction(),
    'Failed to get invoices',
  ],
  [
    'hasActiveSubscriptionAction',
    () => subscription.hasActiveSubscriptionAction(),
    'Failed to check subscription status',
  ],
  [
    'getSubscriptionDetailsAction',
    () => subscription.getSubscriptionDetailsAction(),
    'Failed to get subscription details',
  ],
  [
    'getPaymentMethodsAction',
    () => subscription.getPaymentMethodsAction(),
    'Failed to get payment methods',
  ],
  [
    'deletePaymentMethodAction',
    () => subscription.deletePaymentMethodAction('pm_1'),
    'Failed to remove payment method',
  ],
  [
    'setDefaultPaymentMethodAction',
    () => subscription.setDefaultPaymentMethodAction('pm_1'),
    'Failed to update default payment method',
  ],
];

function expectNoLeak(value: unknown) {
  const serialised = JSON.stringify(value);
  for (const fragment of LEAK_FRAGMENTS) {
    expect(serialised).not.toContain(fragment);
  }
}

describe('KAN-172: legacy server actions return generic errors', () => {
  beforeEach(() => {
    mocks.state.error = SECRET_ERROR;
    mocks.logError.mockReset();
    mocks.getVerifiedUserId.mockReset().mockResolvedValue('user-1');
    mocks.verifySession.mockReset().mockResolvedValue({ uid: 'fb-admin', email_verified: true });
  });

  it.each(ROWS)(
    '%s returns only its generic message when a dependency throws',
    async (_name, call, generic) => {
      const result = await call();

      expect(result.success).toBe(false);
      expect(result.error).toBe(generic);
      expectNoLeak(result);
    }
  );

  it.each(ROWS)('%s hands the original error to the logger', async (_name, call) => {
    await call();

    const logged = mocks.logError.mock.calls.filter((args) => args.includes(SECRET_ERROR));
    expect(logged.length).toBeGreaterThan(0);
    for (const args of logged) {
      expect(typeof args[0]).toBe('string');
      expect(args[0]).not.toContain('SECRET-LEAK');
    }
  });

  describe('unaffected responses', () => {
    it('keeps the Unauthorized string for an unauthenticated user', async () => {
      mocks.getVerifiedUserId.mockResolvedValue(null);

      const result = await subscription.getSubscriptionStatusAction();

      expect(result).toEqual({ success: false, error: 'Unauthorized' });
    });
  });
});
