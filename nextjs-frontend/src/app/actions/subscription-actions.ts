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
  fetchBillingInvoices,
  fetchBillingPaymentMethods,
  fetchBillingSummary,
  resumeBillingSubscription,
  startBillingCheckout,
  startBillingPortal,
} from '@/lib/api/billing';

/**
 * Subscription server actions. Billing state and every Stripe operation live in the FastAPI organisation billing
 * API (KAN-43, KAN-45); this file only authenticates the caller, validates input, builds server-side return URLs
 * and reshapes responses for the existing pages. It no longer touches Prisma or Stripe.
 *
 * KAN-182 (backend): the API does not yet expose the auto-renewal flag (`cancel_at_period_end`), the billing
 * interval, a default-card flag, delete/set-default card routes or an upcoming invoice. Those legacy actions were
 * removed and the matching UI is switched off until KAN-182 lands.
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
};

/** Shown when the user manages no organisation: they are on the free plan. */
const FREE_SUMMARY: PlanSummary = {
  tier: 'free',
  status: 'inactive',
  currentPeriodEnd: null,
  hasBillingAccount: false,
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
    const { plan, subscription_status, current_period_end, has_billing_account } = result.data;
    return {
      success: true,
      data: {
        tier: plan.key,
        status: subscription_status,
        currentPeriodEnd: current_period_end,
        hasBillingAccount: has_billing_account,
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

export async function createCheckoutSessionAction(
  tier: 'pro' | 'enterprise',
  billingPeriod: 'monthly' | 'yearly'
): Promise<SubscriptionActionResponse> {
  try {
    if (!(await getVerifiedUserId())) return UNAUTHORIZED;

    const validation = planChoiceSchema.safeParse({ tier, billingPeriod });
    if (!validation.success) {
      return { success: false, error: validation.error.errors[0].message };
    }

    // Return URLs are built on the server; clients cannot supply them (KAN-127). The backend also checks them
    // against BILLING_RETURN_URL_ORIGINS.
    const { successUrl, cancelUrl } = buildCheckoutReturnUrls();
    const result = await startBillingCheckout(tier, billingPeriod, successUrl, cancelUrl);
    if (!result.success) return failure('Create checkout session error:', result.error);

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

/** Cancel at period end. KAN-182: no UI calls this while the API cannot report the auto-renewal state. */
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

/** Undo a pending cancellation. KAN-182: no UI calls this yet (see cancelSubscriptionAction). */
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

/**
 * Plan details for the billing page. KAN-182: `billingPeriod` and `autoRenewal` are placeholders (null/false)
 * because the API does not return the billing interval or the cancel-at-period-end flag yet.
 */
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
        billingPeriod: null,
        autoRenewal: false,
        currentPeriodEnd: summary.data.currentPeriodEnd,
        hasStripeCustomer: summary.data.hasBillingAccount,
      },
    };
  } catch (error: unknown) {
    logger.error('Get subscription details error:', error);
    return { success: false, error: 'Failed to get subscription details' };
  }
}

/**
 * Saved cards (brand, last4, expiry). KAN-182: the API has no default-card flag, so `isDefault` is always false
 * and the page offers the Stripe portal instead of per-card actions.
 */
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
      isDefault: false,
    }));
    return { success: true, data: { paymentMethods, defaultPaymentMethodId: null } };
  } catch (error: unknown) {
    logger.error('Get payment methods error:', error);
    return { success: false, error: 'Failed to get payment methods' };
  }
}
