// @vitest-environment node
/**
 * KAN-45: the subscription server actions read and change billing only through the organisation billing API wrapper.
 * The wrapper and auth are mocked; these tests pin the reshaping the existing pages rely on.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const NO_ORG = 'No organisation you can manage billing for was found';

const mocks = vi.hoisted(() => ({
  fetchBillingSummary: vi.fn(),
  fetchBillingInvoices: vi.fn(),
  fetchBillingPaymentMethods: vi.fn(),
  startBillingCheckout: vi.fn(),
  startBillingPortal: vi.fn(),
  changeBillingPlan: vi.fn(),
  cancelBillingSubscription: vi.fn(),
  resumeBillingSubscription: vi.fn(),
  deleteBillingPaymentMethod: vi.fn(),
  setDefaultBillingPaymentMethod: vi.fn(),
  getVerifiedUserId: vi.fn(),
  cookieGet: vi.fn(),
  cookieSet: vi.fn(),
  cookieDelete: vi.fn(),
}));

vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({
    get: mocks.cookieGet,
    set: mocks.cookieSet,
    delete: mocks.cookieDelete,
  })),
}));
vi.mock('@/lib/auth/verified-session', () => ({ getVerifiedUserId: mocks.getVerifiedUserId }));
vi.mock('@/lib/logger', () => ({ logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/api/billing', () => ({
  NO_BILLING_ORGANIZATION_MESSAGE: 'No organisation you can manage billing for was found',
  fetchBillingSummary: mocks.fetchBillingSummary,
  fetchBillingInvoices: mocks.fetchBillingInvoices,
  fetchBillingPaymentMethods: mocks.fetchBillingPaymentMethods,
  startBillingCheckout: mocks.startBillingCheckout,
  startBillingPortal: mocks.startBillingPortal,
  changeBillingPlan: mocks.changeBillingPlan,
  cancelBillingSubscription: mocks.cancelBillingSubscription,
  resumeBillingSubscription: mocks.resumeBillingSubscription,
  deleteBillingPaymentMethod: mocks.deleteBillingPaymentMethod,
  setDefaultBillingPaymentMethod: mocks.setDefaultBillingPaymentMethod,
}));

import * as actions from '@/app/actions/subscription-actions';

const PRO_SUMMARY = {
  success: true,
  data: {
    plan: { key: 'pro', name: 'Pro', max_stores: 5, max_products: null, max_staff: 5 },
    subscription_status: 'active',
    current_period_end: '2099-01-01T00:00:00Z',
    has_billing_account: true,
    has_subscription: true,
    cancel_at_period_end: false,
    interval: 'monthly',
  },
};

describe('subscription actions on the billing API', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getVerifiedUserId.mockResolvedValue('user-1');
  });

  it('rejects every action for an unauthenticated user without calling the API', async () => {
    mocks.getVerifiedUserId.mockResolvedValue(null);

    const results = await Promise.all([
      actions.getSubscriptionStatusAction(),
      actions.getSubscriptionDetailsAction(),
      actions.getPaymentMethodsAction(),
      actions.getSubscriptionInvoicesAction(),
      actions.createCheckoutSessionAction('pro', 'monthly'),
      actions.createBillingPortalSessionAction(),
    ]);

    for (const result of results) expect(result).toEqual({ success: false, error: 'Unauthorized' });
    expect(mocks.fetchBillingSummary).not.toHaveBeenCalled();
    expect(mocks.startBillingCheckout).not.toHaveBeenCalled();
  });

  it('maps the plan summary to the details the billing page expects', async () => {
    mocks.fetchBillingSummary.mockResolvedValue(PRO_SUMMARY);

    const result = await actions.getSubscriptionDetailsAction();

    expect(result).toEqual({
      success: true,
      data: {
        subscriptionTier: 'pro',
        subscriptionStatus: 'active',
        stripeStatus: 'active',
        billingPeriod: 'monthly',
        autoRenewal: true,
        currentPeriodEnd: '2099-01-01T00:00:00Z',
        hasStripeCustomer: true,
      },
    });
  });

  it('turns auto-renewal off when the subscription cancels at period end and passes a null interval', async () => {
    mocks.fetchBillingSummary.mockResolvedValue({
      ...PRO_SUMMARY,
      data: { ...PRO_SUMMARY.data, cancel_at_period_end: true, interval: null },
    });

    const result = await actions.getSubscriptionDetailsAction();

    expect(result.data).toMatchObject({ autoRenewal: false, billingPeriod: null });
  });

  it('shows a user with no billable organisation as free', async () => {
    mocks.fetchBillingSummary.mockResolvedValue({ success: false, error: NO_ORG });

    const details = await actions.getSubscriptionDetailsAction();
    const status = await actions.getSubscriptionStatusAction();

    expect(details.data).toMatchObject({ subscriptionTier: 'free', hasStripeCustomer: false });
    expect(status.data).toMatchObject({ subscriptionTier: 'free', subscriptionStatus: 'inactive' });
  });

  it('passes a backend failure message through unchanged', async () => {
    mocks.fetchBillingSummary.mockResolvedValue({ success: false, error: 'Forbidden' });

    expect(await actions.getSubscriptionStatusAction()).toEqual({
      success: false,
      error: 'Forbidden',
    });
  });

  it('reports an active subscription only while the period has not ended', async () => {
    mocks.fetchBillingSummary.mockResolvedValue(PRO_SUMMARY);
    expect((await actions.hasActiveSubscriptionAction()).data).toEqual({
      hasActiveSubscription: true,
    });

    mocks.fetchBillingSummary.mockResolvedValue({
      ...PRO_SUMMARY,
      data: { ...PRO_SUMMARY.data, current_period_end: '2000-01-01T00:00:00Z' },
    });
    expect((await actions.hasActiveSubscriptionAction()).data).toEqual({
      hasActiveSubscription: false,
    });
  });

  it('maps invoices and caps them at the requested limit', async () => {
    const invoice = (id: string) => ({
      id,
      number: id,
      status: 'paid',
      amount_due: 900,
      amount_paid: 900,
      currency: 'usd',
      created: 1_700_000_000,
      hosted_invoice_url: 'https://stripe.test/h',
      invoice_pdf: 'https://stripe.test/p',
    });
    mocks.fetchBillingInvoices.mockResolvedValue({
      success: true,
      data: [invoice('in_1'), invoice('in_2'), invoice('in_3')],
    });

    const result = await actions.getSubscriptionInvoicesAction(2);

    expect(result.data.hasMore).toBe(true);
    expect(result.data.invoices).toHaveLength(2);
    expect(result.data.invoices[0]).toEqual({
      id: 'in_1',
      amount: 900,
      currency: 'usd',
      status: 'paid',
      created: new Date(1_700_000_000 * 1000).toISOString(),
      pdfUrl: 'https://stripe.test/p',
      hostedUrl: 'https://stripe.test/h',
    });
  });

  it('returns empty invoices and cards when the user has no billable organisation', async () => {
    mocks.fetchBillingInvoices.mockResolvedValue({ success: false, error: NO_ORG });
    mocks.fetchBillingPaymentMethods.mockResolvedValue({ success: false, error: NO_ORG });

    expect((await actions.getSubscriptionInvoicesAction()).data.invoices).toEqual([]);
    expect((await actions.getPaymentMethodsAction()).data.paymentMethods).toEqual([]);
  });

  it('maps saved cards and reports which one is the default', async () => {
    mocks.fetchBillingPaymentMethods.mockResolvedValue({
      success: true,
      data: [
        {
          id: 'pm_1',
          brand: 'visa',
          last4: '4242',
          exp_month: 4,
          exp_year: 2030,
          is_default: true,
        },
        {
          id: 'pm_2',
          brand: 'amex',
          last4: '0005',
          exp_month: 1,
          exp_year: 2031,
          is_default: false,
        },
      ],
    });

    const result = await actions.getPaymentMethodsAction();

    expect(result.data.paymentMethods).toEqual([
      { id: 'pm_1', brand: 'visa', last4: '4242', expMonth: 4, expYear: 2030, isDefault: true },
      { id: 'pm_2', brand: 'amex', last4: '0005', expMonth: 1, expYear: 2031, isDefault: false },
    ]);
    expect(result.data.defaultPaymentMethodId).toBe('pm_1');
  });

  describe('card actions', () => {
    it('removes a card through the API', async () => {
      mocks.deleteBillingPaymentMethod.mockResolvedValue({
        success: true,
        data: { success: true },
      });

      const result = await actions.deletePaymentMethodAction('pm_2');

      expect(result).toEqual({ success: true, data: { message: 'Payment method removed' } });
      expect(mocks.deleteBillingPaymentMethod).toHaveBeenCalledWith('pm_2');
    });

    it('shows the backend 409 for the default card of a live subscription', async () => {
      const message = 'Cannot delete the default payment method while subscribed';
      mocks.deleteBillingPaymentMethod.mockResolvedValue({ success: false, error: message });

      expect(await actions.deletePaymentMethodAction('pm_1')).toEqual({
        success: false,
        error: message,
      });
    });

    it('sets the default card through the API', async () => {
      mocks.setDefaultBillingPaymentMethod.mockResolvedValue({
        success: true,
        data: { success: true },
      });

      const result = await actions.setDefaultPaymentMethodAction('pm_2');

      expect(result).toEqual({
        success: true,
        data: { message: 'Default payment method updated' },
      });
      expect(mocks.setDefaultBillingPaymentMethod).toHaveBeenCalledWith('pm_2');
    });

    it('rejects a malformed id and an unauthenticated caller before calling the API', async () => {
      expect((await actions.deletePaymentMethodAction('../x')).success).toBe(false);
      expect((await actions.setDefaultPaymentMethodAction('card_1')).success).toBe(false);

      mocks.getVerifiedUserId.mockResolvedValue(null);
      expect(await actions.deletePaymentMethodAction('pm_1')).toEqual({
        success: false,
        error: 'Unauthorized',
      });
      expect(mocks.deleteBillingPaymentMethod).not.toHaveBeenCalled();
      expect(mocks.setDefaultBillingPaymentMethod).not.toHaveBeenCalled();
    });
  });

  describe('checkout', () => {
    it('returns the Stripe URL and sets the httpOnly checkout token', async () => {
      mocks.startBillingCheckout.mockResolvedValue({
        success: true,
        data: { url: 'https://checkout.stripe.test/s' },
      });

      const result = await actions.createCheckoutSessionAction('pro', 'yearly');

      expect(result).toEqual({ success: true, data: { url: 'https://checkout.stripe.test/s' } });
      expect(mocks.startBillingCheckout.mock.calls[0].slice(0, 2)).toEqual(['pro', 'yearly']);
      expect(mocks.cookieSet).toHaveBeenCalledWith(
        'checkout_token',
        expect.stringMatching(/^[0-9a-f]{64}$/),
        expect.objectContaining({ httpOnly: true, sameSite: 'lax', maxAge: 600 })
      );
    });

    it('rejects an unknown plan before calling the API', async () => {
      const result = await actions.createCheckoutSessionAction(
        'gold' as unknown as 'pro',
        'monthly'
      );

      expect(result.success).toBe(false);
      expect(mocks.startBillingCheckout).not.toHaveBeenCalled();
    });

    it('relays a backend rule such as an existing subscription and sets no token', async () => {
      mocks.startBillingCheckout.mockResolvedValue({
        success: false,
        error: 'Subscription already exists',
      });

      const result = await actions.createCheckoutSessionAction('pro', 'monthly');

      expect(result).toEqual({ success: false, error: 'Subscription already exists' });
      expect(mocks.cookieSet).not.toHaveBeenCalled();
    });
  });

  describe('verifyUpgradeSessionAction', () => {
    it('is invalid without the checkout token a real checkout sets', async () => {
      mocks.cookieGet.mockReturnValue(undefined);

      const result = await actions.verifyUpgradeSessionAction();

      expect(result.data?.valid).toBe(false);
      expect(mocks.cookieDelete).not.toHaveBeenCalled();
    });

    it('is valid once and consumes the token', async () => {
      mocks.cookieGet.mockReturnValue({ value: 'token' });

      const result = await actions.verifyUpgradeSessionAction();

      expect(result.data).toEqual({ valid: true });
      expect(mocks.cookieDelete).toHaveBeenCalledWith('checkout_token');
    });
  });

  it('opens the billing portal with the server-built return URL', async () => {
    mocks.startBillingPortal.mockResolvedValue({
      success: true,
      data: { url: 'https://billing.stripe.test/p' },
    });

    const result = await actions.createBillingPortalSessionAction();

    expect(result).toEqual({ success: true, data: { url: 'https://billing.stripe.test/p' } });
    expect(mocks.startBillingPortal).toHaveBeenCalledWith(
      expect.stringMatching(/\/dashboard\/settings\/billing$/)
    );
  });

  it('changes plan, cancels and resumes through the API', async () => {
    mocks.changeBillingPlan.mockResolvedValue({ success: true, data: { success: true } });
    mocks.cancelBillingSubscription.mockResolvedValue({ success: true, data: { success: true } });
    mocks.resumeBillingSubscription.mockResolvedValue({
      success: false,
      error: 'No pending cancellation',
    });

    expect((await actions.updateSubscriptionAction('enterprise', 'monthly')).success).toBe(true);
    expect(mocks.changeBillingPlan).toHaveBeenCalledWith('enterprise', 'monthly');
    expect((await actions.cancelSubscriptionAction()).success).toBe(true);
    expect(await actions.resumeSubscriptionAction()).toEqual({
      success: false,
      error: 'No pending cancellation',
    });
  });
});
