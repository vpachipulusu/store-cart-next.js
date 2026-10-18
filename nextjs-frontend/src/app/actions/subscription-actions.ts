'use server';

import { cookies } from 'next/headers';
import { z } from 'zod';
import crypto from 'crypto';
import { logger } from '@/lib/logger';
import { getVerifiedUserId } from '@/lib/auth/verified-session';
import { buildBillingPortalReturnUrl, buildCheckoutReturnUrls } from '@/lib/stripe/return-urls';
import {
  NO_BILLING_ORGANIZATION_MESSAGE,
  cancelBillingSubscription,
  changeBillingPlan,
  deleteBillingPaymentMethod,
  fetchBillingInvoices,
  fetchBillingPaymentMethods,
  fetchBillingSummary,
  resumeBillingSubscription,
  setDefaultBillingPaymentMethod,
  startBillingCheckout,
  startBillingPortal,
} from '@/lib/api/billing';

/**
 * Subscription server actions. Billing state and every Stripe operation live in the FastAPI organisation billing
 * API (KAN-43, KAN-45); this file only authenticates the caller, validates input, builds server-side return URLs
 * and reshapes responses for the existing pages. It no longer touches Prisma or Stripe.
 *
 * The API has no upcoming-invoice route, so that legacy action stays removed and its panel stays switched off.
 */

type SubscriptionActionResponse<T = any> = {
  success: boolean;
  data?: T;
  error?: string;
};

const UNAUTHORIZED = { success: false, error: 'Unauthorized' } as const;

type PlanSummary = {
  tier: string;
  status: string;
  currentPeriodEnd: string | null;
  hasBillingAccount: boolean;
  cancelAtPeriodEnd: boolean;
  /** `null` when the price id is not in the backend's price catalogue. */
  interval: 'monthly' | 'yearly' | null;
};

/** Shown when the user manages no organisation: they are on the free plan. */
const FREE_SUMMARY: PlanSummary = {
  tier: 'free',
  status: 'inactive',
  currentPeriodEnd: null,
  hasBillingAccount: false,
  cancelAtPeriodEnd: false,
  interval: null,
};

const planChoiceSchema = z.object({
  tier: z.enum(['pro', 'enterprise']),
  billingPeriod: z.enum(['monthly', 'yearly']),
});

/** Reads the organisation plan; a user without a billable organisation is shown as free. */
async function loadPlanSummary(): Promise<
  { success: true; data: PlanSummary } | { success: false; error: string }
> {
  const result = await fetchBillingSummary();
  if (result.success) {
    const {
      plan,
      subscription_status,
      current_period_end,
      has_billing_account,
      cancel_at_period_end,
      interval,
    } = result.data;
    return {
      success: true,
      data: {
        tier: plan.key,
        status: subscription_status,
        currentPeriodEnd: current_period_end,
        hasBillingAccount: has_billing_account,
        cancelAtPeriodEnd: cancel_at_period_end,
        interval,
      },
    };
  }
  if (result.error === NO_BILLING_ORGANIZATION_MESSAGE) {
    return { success: true, data: FREE_SUMMARY };
  }
  return result;
}

/** Logs and returns the backend's own envelope message (409 rules, 403, 503 ...), which is curated, never raw. */
function failure(logMessage: string, error: string): SubscriptionActionResponse {
  logger.error(logMessage, { error });
  return { success: false, error };
}

export async function getSubscriptionStatusAction(): Promise<SubscriptionActionResponse> {
  try {
    if (!(await getVerifiedUserId())) return UNAUTHORIZED;

    const summary = await loadPlanSummary();
    if (!summary.success) return failure('Get subscription status error:', summary.error);

    return {
      success: true,
      data: {
        subscriptionTier: summary.data.tier,
        subscriptionStatus: summary.data.status,
        currentPeriodEnd: summary.data.currentPeriodEnd,
        stripeSubscription: null,
      },
    };
  } catch (error: unknown) {
    logger.error('Get subscription status error:', error);
    return { success: false, error: 'Failed to get subscription status' };
  }
}

type CheckoutFailureCode =
  | 'no_organization'
  | 'return_url_config'
  | 'invalid_return_url'
  | 'not_configured'
  | 'provider_unavailable'
  | 'not_allowed'
  | 'forbidden'
  | 'session_expired'
  | 'backend_unavailable'
  | 'unknown';

/** What the pricing page shows for each cause. Curated here, so no backend or Stripe text reaches the browser. */
const CHECKOUT_FAILURE_MESSAGES: Record<CheckoutFailureCode, string> = {
  no_organization:
    'Create a store first to subscribe. Billing is tied to your organisation, which is set up when you create a store.',
  return_url_config: 'Checkout is not available right now. Please try again later.',
  invalid_return_url: 'Checkout is not available right now. Please try again later.',
  not_configured: 'Checkout is not available right now. Please try again later.',
  provider_unavailable:
    'We could not reach our payment provider. Please try again in a few minutes.',
  not_allowed:
    'Checkout is not available for your organisation right now. If it already has a subscription, manage it from Billing settings.',
  forbidden:
    'We could not find a billing organisation you manage. Only an organisation owner or admin can change the plan.',
  session_expired: 'Your session has expired. Please sign in again.',
  backend_unavailable: 'We could not reach the billing service. Please try again.',
  unknown: 'We could not start checkout. Please try again.',
};

/** The cause of a failed checkout call, from the backend status (see the HTTP mapping in org_billing.py). */
function classifyCheckoutFailure(error: string, status?: number): CheckoutFailureCode {
  if (error === NO_BILLING_ORGANIZATION_MESSAGE) return 'no_organization';
  // No status means the backend never answered (unreachable or timed out).
  if (status === undefined) return 'backend_unavailable';
  switch (status) {
    case 422:
      return 'invalid_return_url';
    case 503:
      return 'not_configured';
    case 502:
      return 'provider_unavailable';
    case 409:
      return 'not_allowed';
    case 401:
      return 'session_expired';
    case 403:
    case 404:
      return 'forbidden';
    default:
      return 'unknown';
  }
}

/** Logs the cause (class, status, code; never secrets, ids or backend text) and returns the curated response. */
function checkoutFailure(
  code: CheckoutFailureCode,
  details: { status?: number; cause?: string }
): SubscriptionActionResponse & { code: CheckoutFailureCode } {
  logger.error('Create checkout session failed:', { code, ...details });
  return { success: false, error: CHECKOUT_FAILURE_MESSAGES[code], code };
}

function errorClass(error: unknown): string {
  return error instanceof Error ? error.constructor.name : typeof error;
}

export async function createCheckoutSessionAction(
  tier: 'pro' | 'enterprise',
  billingPeriod: 'monthly' | 'yearly'
): Promise<SubscriptionActionResponse & { code?: CheckoutFailureCode }> {
  try {
    if (!(await getVerifiedUserId())) {
      return {
        success: false,
        error: CHECKOUT_FAILURE_MESSAGES.session_expired,
        code: 'session_expired',
      };
    }

    const validation = planChoiceSchema.safeParse({ tier, billingPeriod });
    if (!validation.success) {
      return { success: false, error: validation.error.errors[0].message };
    }

    // Return URLs are built on the server; clients cannot supply them (KAN-127). The backend also checks them
    // against BILLING_RETURN_URL_ORIGINS.
    let urls: ReturnType<typeof buildCheckoutReturnUrls>;
    try {
      urls = buildCheckoutReturnUrls();
    } catch (error: unknown) {
      return checkoutFailure('return_url_config', { cause: errorClass(error) });
    }

    const result = await startBillingCheckout(tier, billingPeriod, urls.successUrl, urls.cancelUrl);
    if (!result.success) {
      const status = 'status' in result ? result.status : undefined;
      return checkoutFailure(classifyCheckoutFailure(result.error, status), { status });
    }

    // httpOnly token proving this browser started a checkout, so ?upgrade=success cannot be forged by hand.
    const cookieStore = await cookies();
    cookieStore.set('checkout_token', crypto.randomBytes(32).toString('hex'), {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 600, // 10 minutes
      path: '/',
    });

    return { success: true, data: { url: result.data.url } };
  } catch (error: unknown) {
    logger.error('Create checkout session error:', error);
    return { success: false, error: 'Failed to create checkout session' };
  }
}

/**
 * Verify checkout session for upgrade success. Prevents users from manually navigating to ?upgrade=success: only
 * the browser that started a checkout holds the short-lived httpOnly token. The webhook (the only writer of plan
 * state) can lag behind the redirect, so the plan itself is polled afterwards by the success handler.
 */
export async function verifyUpgradeSessionAction(): Promise<
  SubscriptionActionResponse<{ valid: boolean; reason?: string }>
> {
  try {
    if (!(await getVerifiedUserId())) return UNAUTHORIZED;

    const cookieStore = await cookies();
    if (!cookieStore.get('checkout_token')?.value) {
      return {
        success: true,
        data: { valid: false, reason: 'No valid checkout session found' },
      };
    }

    cookieStore.delete('checkout_token');
    return { success: true, data: { valid: true } };
  } catch (error: unknown) {
    logger.error('Verify upgrade session error:', error);
    return { success: false, error: 'Failed to verify upgrade session' };
  }
}

export async function createBillingPortalSessionAction(): Promise<SubscriptionActionResponse> {
  try {
    if (!(await getVerifiedUserId())) return UNAUTHORIZED;

    const result = await startBillingPortal(buildBillingPortalReturnUrl());
    if (!result.success) return failure('Create billing portal session error:', result.error);
    return { success: true, data: { url: result.data.url } };
  } catch (error: unknown) {
    logger.error('Create billing portal session error:', error);
    return { success: false, error: 'Failed to create billing portal session' };
  }
}

/** Cancel at period end (auto-renewal off). */
export async function cancelSubscriptionAction(): Promise<SubscriptionActionResponse> {
  try {
    if (!(await getVerifiedUserId())) return UNAUTHORIZED;

    const result = await cancelBillingSubscription();
    if (!result.success) return failure('Cancel subscription error:', result.error);
    return {
      success: true,
      data: { message: 'Subscription will be canceled at the end of the billing period' },
    };
  } catch (error: unknown) {
    logger.error('Cancel subscription error:', error);
    return { success: false, error: 'Failed to cancel subscription' };
  }
}

/** Undo a pending cancellation (auto-renewal on). */
export async function resumeSubscriptionAction(): Promise<SubscriptionActionResponse> {
  try {
    if (!(await getVerifiedUserId())) return UNAUTHORIZED;

    const result = await resumeBillingSubscription();
    if (!result.success) return failure('Resume subscription error:', result.error);
    return { success: true, data: { message: 'Subscription resumed successfully' } };
  } catch (error: unknown) {
    logger.error('Resume subscription error:', error);
    return { success: false, error: 'Failed to resume subscription' };
  }
}

/** Change plan or interval on the live subscription (prorated by the backend). */
export async function updateSubscriptionAction(
  tier: 'pro' | 'enterprise',
  billingPeriod: 'monthly' | 'yearly'
): Promise<SubscriptionActionResponse> {
  try {
    if (!(await getVerifiedUserId())) return UNAUTHORIZED;

    const validation = planChoiceSchema.safeParse({ tier, billingPeriod });
    if (!validation.success) {
      return { success: false, error: validation.error.errors[0].message };
    }

    const result = await changeBillingPlan(tier, billingPeriod);
    if (!result.success) return failure('Update subscription error:', result.error);
    return { success: true, data: { message: 'Subscription updated successfully' } };
  } catch (error: unknown) {
    logger.error('Update subscription error:', error);
    return { success: false, error: 'Failed to update subscription' };
  }
}

/** Latest invoices (the API returns up to 12). */
export async function getSubscriptionInvoicesAction(
  limit = 10
): Promise<SubscriptionActionResponse> {
  try {
    if (!(await getVerifiedUserId())) return UNAUTHORIZED;

    const result = await fetchBillingInvoices();
    if (!result.success) {
      if (result.error === NO_BILLING_ORGANIZATION_MESSAGE) {
        return { success: true, data: { invoices: [], hasMore: false } };
      }
      return failure('Get invoices error:', result.error);
    }

    const invoices = result.data.slice(0, limit).map((invoice) => ({
      id: invoice.id,
      amount: invoice.amount_paid,
      currency: invoice.currency,
      status: invoice.status,
      created: new Date(invoice.created * 1000).toISOString(),
      pdfUrl: invoice.invoice_pdf,
      hostedUrl: invoice.hosted_invoice_url,
    }));
    return { success: true, data: { invoices, hasMore: result.data.length > limit } };
  } catch (error: unknown) {
    logger.error('Get invoices error:', error);
    return { success: false, error: 'Failed to get invoices' };
  }
}

export async function hasActiveSubscriptionAction(): Promise<SubscriptionActionResponse> {
  try {
    if (!(await getVerifiedUserId())) return UNAUTHORIZED;

    const summary = await loadPlanSummary();
    if (!summary.success) return failure('Check active subscription error:', summary.error);

    const { status, currentPeriodEnd } = summary.data;
    const hasActive =
      status === 'active' && currentPeriodEnd !== null && new Date(currentPeriodEnd) > new Date();
    return { success: true, data: { hasActiveSubscription: hasActive } };
  } catch (error: unknown) {
    logger.error('Check active subscription error:', error);
    return { success: false, error: 'Failed to check subscription status' };
  }
}

/** Plan details for the billing page; `billingPeriod` is null when the price is not in the catalogue. */
export async function getSubscriptionDetailsAction(): Promise<SubscriptionActionResponse> {
  try {
    if (!(await getVerifiedUserId())) return UNAUTHORIZED;

    const summary = await loadPlanSummary();
    if (!summary.success) return failure('Get subscription details error:', summary.error);

    return {
      success: true,
      data: {
        subscriptionTier: summary.data.tier,
        subscriptionStatus: summary.data.status,
        stripeStatus: summary.data.status,
        billingPeriod: summary.data.interval,
        autoRenewal: summary.data.status === 'active' && !summary.data.cancelAtPeriodEnd,
        currentPeriodEnd: summary.data.currentPeriodEnd,
        hasStripeCustomer: summary.data.hasBillingAccount,
      },
    };
  } catch (error: unknown) {
    logger.error('Get subscription details error:', error);
    return { success: false, error: 'Failed to get subscription details' };
  }
}

/** Saved cards (brand, last4, expiry, default flag as read live from Stripe). */
export async function getPaymentMethodsAction(): Promise<SubscriptionActionResponse> {
  try {
    if (!(await getVerifiedUserId())) return UNAUTHORIZED;

    const result = await fetchBillingPaymentMethods();
    if (!result.success) {
      if (result.error === NO_BILLING_ORGANIZATION_MESSAGE) {
        return { success: true, data: { paymentMethods: [], defaultPaymentMethodId: null } };
      }
      return failure('Get payment methods error:', result.error);
    }

    const paymentMethods = result.data.map((method) => ({
      id: method.id,
      brand: method.brand ?? 'unknown',
      last4: method.last4 ?? '****',
      expMonth: method.exp_month ?? 0,
      expYear: method.exp_year ?? 0,
      isDefault: method.is_default,
    }));
    const defaultPaymentMethodId = paymentMethods.find((method) => method.isDefault)?.id ?? null;
    return { success: true, data: { paymentMethods, defaultPaymentMethodId } };
  } catch (error: unknown) {
    logger.error('Get payment methods error:', error);
    return { success: false, error: 'Failed to get payment methods' };
  }
}

const paymentMethodIdSchema = z.string().regex(/^pm_[A-Za-z0-9_]+$/, 'Invalid payment method');

/** Detaches a saved card. The backend refuses (409) to remove the default card while a subscription is live. */
export async function deletePaymentMethodAction(
  paymentMethodId: string
): Promise<SubscriptionActionResponse> {
  try {
    if (!(await getVerifiedUserId())) return UNAUTHORIZED;

    const validation = paymentMethodIdSchema.safeParse(paymentMethodId);
    if (!validation.success) return { success: false, error: validation.error.errors[0].message };

    const result = await deleteBillingPaymentMethod(validation.data);
    if (!result.success) return failure('Delete payment method error:', result.error);
    return { success: true, data: { message: 'Payment method removed' } };
  } catch (error: unknown) {
    logger.error('Delete payment method error:', error);
    return { success: false, error: 'Failed to remove payment method' };
  }
}

/** Makes a saved card the default used for renewals. */
export async function setDefaultPaymentMethodAction(
  paymentMethodId: string
): Promise<SubscriptionActionResponse> {
  try {
    if (!(await getVerifiedUserId())) return UNAUTHORIZED;

    const validation = paymentMethodIdSchema.safeParse(paymentMethodId);
    if (!validation.success) return { success: false, error: validation.error.errors[0].message };

    const result = await setDefaultBillingPaymentMethod(validation.data);
    if (!result.success) return failure('Set default payment method error:', result.error);
    return { success: true, data: { message: 'Default payment method updated' } };
  } catch (error: unknown) {
    logger.error('Set default payment method error:', error);
    return { success: false, error: 'Failed to update default payment method' };
  }
}
