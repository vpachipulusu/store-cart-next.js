'use server';

import { cookies } from 'next/headers';
import { z } from 'zod';
import Stripe from 'stripe';
import { adminAuth } from '@/lib/firebase/admin';
import { db } from '@/lib/db/client';
import crypto from 'crypto';
import { logger } from '@/lib/logger';

/**
 * Initialize Stripe
 */
const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: '2025-08-27.basil',
  typescript: true,
});

/**
 * Response type for subscription actions
 */
type SubscriptionActionResponse<T = any> = {
  success: boolean;
  data?: T;
  error?: string;
};

/**
 * Get authenticated user ID from session
 */
async function getAuthenticatedUserId(): Promise<string | null> {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get('session')?.value;

    if (!sessionCookie) {
      return null;
    }

    const decodedClaims = await adminAuth.verifySessionCookie(sessionCookie, true);
    const user = await db.user.findUnique({
      where: { firebaseUid: decodedClaims.uid },
      select: { id: true },
    });

    return user?.id || null;
  } catch (error) {
    logger.error('Authentication error:', error);
    return null;
  }
}

/**
 * Server-side price ID mapping (env vars are only available on the server)
 */
const PRICE_IDS: Record<string, { monthly: string; yearly: string }> = {
  pro: {
    monthly: process.env.STRIPE_PRICE_ID_PRO_MONTHLY || '',
    yearly: process.env.STRIPE_PRICE_ID_PRO_YEARLY || '',
  },
  enterprise: {
    monthly: process.env.STRIPE_PRICE_ID_ENTERPRISE_MONTHLY || '',
    yearly: process.env.STRIPE_PRICE_ID_ENTERPRISE_YEARLY || '',
  },
};

/**
 * Safely extract the period end timestamp from a Stripe subscription.
 * Handles different Stripe API versions where property names may vary.
 */
function getSubscriptionPeriodEnd(subscription: any): Date | null {
  const timestamp =
    subscription.current_period_end ??
    subscription.currentPeriodEnd ??
    subscription.current_period?.end;

  if (typeof timestamp === 'number' && timestamp > 0) {
    return new Date(timestamp * 1000);
  }
  return null;
}

/**
 * Extract a customer ID string from a Stripe customer field
 * which may be a string, Customer object, or null.
 */
function extractCustomerId(customer: string | { id: string } | null | undefined): string | null {
  if (!customer) return null;
  if (typeof customer === 'string') return customer;
  if (typeof customer === 'object' && 'id' in customer) return customer.id;
  return null;
}

/**
 * Create checkout session schema
 */
const createCheckoutSessionSchema = z.object({
  tier: z.enum(['pro', 'enterprise']),
  billingPeriod: z.enum(['monthly', 'yearly']),
  successUrl: z.string().url(),
  cancelUrl: z.string().url(),
});

/**
 * Get subscription status
 */
export async function getSubscriptionStatusAction(): Promise<SubscriptionActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
      select: {
        subscriptionTier: true,
        subscriptionStatus: true,
        stripeSubscriptionId: true,
        stripePriceId: true,
        stripeCurrentPeriodEnd: true,
      },
    });

    if (!user) {
      return {
        success: false,
        error: 'User not found',
      };
    }

    let subscriptionDetails = null;

    // Get detailed subscription info from Stripe if exists
    if (user.stripeSubscriptionId) {
      try {
        const subscription = await stripe.subscriptions.retrieve(user.stripeSubscriptionId);
        subscriptionDetails = {
          id: subscription.id,
          status: subscription.status,
          currentPeriodEnd: getSubscriptionPeriodEnd(subscription)?.toISOString() ?? null,
          cancelAtPeriodEnd: subscription.cancel_at_period_end,
          canceledAt: subscription.canceled_at
            ? new Date(subscription.canceled_at * 1000).toISOString()
            : null,
        };
      } catch (error) {
        logger.error('Failed to retrieve Stripe subscription:', error);
      }
    }

    return {
      success: true,
      data: {
        subscriptionTier: user.subscriptionTier,
        subscriptionStatus: user.subscriptionStatus,
        currentPeriodEnd: user.stripeCurrentPeriodEnd,
        stripeSubscription: subscriptionDetails,
      },
    };
  } catch (error: any) {
    logger.error('Get subscription status error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get subscription status',
    };
  }
}

/**
 * Create Stripe checkout session
 */
export async function createCheckoutSessionAction(
  tier: 'pro' | 'enterprise',
  billingPeriod: 'monthly' | 'yearly',
  successUrl: string,
  cancelUrl: string
): Promise<SubscriptionActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Validate input
    const validation = createCheckoutSessionSchema.safeParse({
      tier,
      billingPeriod,
      successUrl,
      cancelUrl,
    });

    if (!validation.success) {
      return {
        success: false,
        error: validation.error.errors[0].message,
      };
    }

    // Resolve price ID on the server
    const priceId = PRICE_IDS[tier]?.[billingPeriod];
    if (!priceId) {
      return {
        success: false,
        error: `Price not configured for ${tier} ${billingPeriod} plan`,
      };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
    });

    if (!user) {
      return {
        success: false,
        error: 'User not found',
      };
    }

    // Create or retrieve Stripe customer
    let customerId = user.stripeCustomerId;

    if (!customerId) {
      const customer = await stripe.customers.create({
        email: user.email,
        metadata: {
          userId: user.id,
          firebaseUid: user.firebaseUid,
        },
      });

      customerId = customer.id;

      // Update user with Stripe customer ID
      await db.user.update({
        where: { id: userId },
        data: { stripeCustomerId: customerId },
      });
    }

    // Create checkout session
    const session = await stripe.checkout.sessions.create({
      customer: customerId,
      payment_method_types: ['card'],
      line_items: [
        {
          price: priceId,
          quantity: 1,
        },
      ],
      mode: 'subscription',
      success_url: successUrl,
      cancel_url: cancelUrl,
      metadata: {
        userId: user.id,
      },
    });

    // Generate secure checkout token to prevent URL manipulation
    const checkoutToken = crypto.randomBytes(32).toString('hex');
    const cookieStore = await cookies();

    // Store checkout token in HTTP-only cookie (expires in 10 minutes)
    cookieStore.set('checkout_token', checkoutToken, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 600, // 10 minutes
      path: '/',
    });

    // Store session ID mapping
    cookieStore.set('checkout_session', session.id, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 600, // 10 minutes
      path: '/',
    });

    return {
      success: true,
      data: {
        sessionId: session.id,
        url: session.url,
      },
    };
  } catch (error: any) {
    logger.error('Create checkout session error:', error);
    return {
      success: false,
      error: error.message || 'Failed to create checkout session',
    };
  }
}

/**
 * Verify checkout session for upgrade success
 * Prevents users from manually navigating to ?upgrade=success
 */
export async function verifyUpgradeSessionAction(): Promise<
  SubscriptionActionResponse<{
    valid: boolean;
    reason?: string;
  }>
> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const cookieStore = await cookies();
    const checkoutToken = cookieStore.get('checkout_token')?.value;
    const checkoutSession = cookieStore.get('checkout_session')?.value;

    // If no checkout token, this is a manual/fake URL
    if (!checkoutToken || !checkoutSession) {
      return {
        success: true,
        data: {
          valid: false,
          reason: 'No valid checkout session found',
        },
      };
    }

    // Check if user's subscription was recently updated (within last 5 minutes)
    const user = await db.user.findUnique({
      where: { id: userId },
      select: {
        subscriptionTier: true,
        subscriptionStatus: true,
        updatedAt: true,
      },
    });

    if (!user) {
      return {
        success: false,
        error: 'User not found',
      };
    }

    const fiveMinutesAgo = new Date(Date.now() - 5 * 60 * 1000);
    const wasRecentlyUpdated = user.updatedAt > fiveMinutesAgo;

    // Valid if: has checkout token AND (subscription was recently updated OR is already upgraded)
    const isValid = !!checkoutToken && (wasRecentlyUpdated || user.subscriptionTier !== 'free');

    // Clear checkout tokens after verification
    if (isValid) {
      cookieStore.delete('checkout_token');
      cookieStore.delete('checkout_session');
    }

    return {
      success: true,
      data: {
        valid: isValid,
        reason: isValid ? undefined : 'Invalid or expired checkout session',
      },
    };
  } catch (error: any) {
    logger.error('Verify upgrade session error:', error);
    return {
      success: false,
      error: error.message || 'Failed to verify upgrade session',
    };
  }
}

/**
 * Create billing portal session
 */
export async function createBillingPortalSessionAction(
  returnUrl: string
): Promise<SubscriptionActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
      select: { stripeCustomerId: true },
    });

    if (!user || !user.stripeCustomerId) {
      return {
        success: false,
        error: 'No billing information found',
      };
    }

    // Create billing portal session
    const session = await stripe.billingPortal.sessions.create({
      customer: user.stripeCustomerId,
      return_url: returnUrl,
    });

    return {
      success: true,
      data: {
        url: session.url,
      },
    };
  } catch (error: any) {
    logger.error('Create billing portal session error:', error);
    return {
      success: false,
      error: error.message || 'Failed to create billing portal session',
    };
  }
}

/**
 * Cancel subscription
 */
export async function cancelSubscriptionAction(): Promise<SubscriptionActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
      select: { stripeSubscriptionId: true },
    });

    if (!user || !user.stripeSubscriptionId) {
      return {
        success: false,
        error: 'No active subscription found',
      };
    }

    // Cancel subscription at period end
    const subscription = await stripe.subscriptions.update(user.stripeSubscriptionId, {
      cancel_at_period_end: true,
    });

    return {
      success: true,
      data: {
        message: 'Subscription will be canceled at the end of the billing period',
        cancelAt: new Date((subscription as any).current_period_end * 1000),
      },
    };
  } catch (error: any) {
    logger.error('Cancel subscription error:', error);
    return {
      success: false,
      error: error.message || 'Failed to cancel subscription',
    };
  }
}

/**
 * Resume subscription (undo cancellation)
 */
export async function resumeSubscriptionAction(): Promise<SubscriptionActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
      select: { stripeSubscriptionId: true },
    });

    if (!user || !user.stripeSubscriptionId) {
      return {
        success: false,
        error: 'No subscription found',
      };
    }

    // First check current subscription state
    const currentSub = await stripe.subscriptions.retrieve(user.stripeSubscriptionId);

    // Can only resume if subscription is in a valid state
    if (currentSub.status === 'canceled') {
      return {
        success: false,
        error:
          'This subscription has already been canceled and cannot be resumed. Please subscribe again from the pricing page.',
      };
    }

    if (currentSub.status === 'incomplete' || currentSub.status === 'incomplete_expired') {
      return {
        success: false,
        error:
          'This subscription was never completed. Please subscribe again from the pricing page.',
      };
    }

    if (currentSub.status !== 'active') {
      return {
        success: false,
        error: `Subscription status is ${currentSub.status}. Only active subscriptions can be managed.`,
      };
    }

    // If already not set to cancel, it's already active
    if (!currentSub.cancel_at_period_end) {
      return {
        success: true,
        data: { message: 'Subscription is already active' },
      };
    }

    // Resume subscription
    await stripe.subscriptions.update(user.stripeSubscriptionId, {
      cancel_at_period_end: false,
    });

    return {
      success: true,
      data: {
        message: 'Subscription resumed successfully',
      },
    };
  } catch (error: any) {
    logger.error('Resume subscription error:', error);
    return {
      success: false,
      error: error.message || 'Failed to resume subscription',
    };
  }
}

/**
 * Update subscription (change plan)
 */
export async function updateSubscriptionAction(
  newPriceId: string
): Promise<SubscriptionActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
      select: { stripeSubscriptionId: true },
    });

    if (!user || !user.stripeSubscriptionId) {
      return {
        success: false,
        error: 'No active subscription found',
      };
    }

    // Get current subscription
    const subscription = await stripe.subscriptions.retrieve(user.stripeSubscriptionId);

    // Update subscription with new price
    const updatedSubscription = await stripe.subscriptions.update(user.stripeSubscriptionId, {
      items: [
        {
          id: subscription.items.data[0].id,
          price: newPriceId,
        },
      ],
      proration_behavior: 'create_prorations',
    });

    return {
      success: true,
      data: {
        message: 'Subscription updated successfully',
        subscription: {
          id: updatedSubscription.id,
          status: updatedSubscription.status,
        },
      },
    };
  } catch (error: any) {
    logger.error('Update subscription error:', error);
    return {
      success: false,
      error: error.message || 'Failed to update subscription',
    };
  }
}

/**
 * Get subscription invoices
 */
export async function getSubscriptionInvoicesAction(
  limit = 10
): Promise<SubscriptionActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
      select: { stripeCustomerId: true },
    });

    if (!user || !user.stripeCustomerId) {
      return {
        success: false,
        error: 'No billing information found',
      };
    }

    // Get invoices from Stripe
    const invoices = await stripe.invoices.list({
      customer: user.stripeCustomerId,
      limit,
    });

    const formattedInvoices = invoices.data.map((invoice) => ({
      id: invoice.id,
      amount: invoice.amount_paid,
      currency: invoice.currency,
      status: invoice.status,
      created: new Date(invoice.created * 1000),
      pdfUrl: invoice.invoice_pdf,
      hostedUrl: invoice.hosted_invoice_url,
    }));

    return {
      success: true,
      data: {
        invoices: formattedInvoices,
        hasMore: invoices.has_more,
      },
    };
  } catch (error: any) {
    logger.error('Get invoices error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get invoices',
    };
  }
}

/**
 * Get upcoming invoice
 */
export async function getUpcomingInvoiceAction(): Promise<SubscriptionActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
      select: { stripeCustomerId: true, stripeSubscriptionId: true },
    });

    if (!user || !user.stripeCustomerId || !user.stripeSubscriptionId) {
      return {
        success: false,
        error: 'No active subscription found',
      };
    }

    // Get upcoming invoice
    const invoice = await (stripe.invoices as any).retrieveUpcoming({
      customer: user.stripeCustomerId,
      subscription: user.stripeSubscriptionId,
    });

    return {
      success: true,
      data: {
        amount: invoice.amount_due,
        currency: invoice.currency,
        periodEnd: new Date(invoice.period_end * 1000),
      },
    };
  } catch (error: any) {
    logger.error('Get upcoming invoice error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get upcoming invoice',
    };
  }
}

/**
 * Check if user has active subscription
 */
export async function hasActiveSubscriptionAction(): Promise<SubscriptionActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
      select: {
        subscriptionStatus: true,
        stripeCurrentPeriodEnd: true,
      },
    });

    if (!user) {
      return {
        success: false,
        error: 'User not found',
      };
    }

    const hasActive =
      user.subscriptionStatus === 'active' &&
      user.stripeCurrentPeriodEnd &&
      user.stripeCurrentPeriodEnd > new Date();

    return {
      success: true,
      data: {
        hasActiveSubscription: hasActive,
      },
    };
  } catch (error: any) {
    logger.error('Check active subscription error:', error);
    return {
      success: false,
      error: error.message || 'Failed to check subscription status',
    };
  }
}

/**
 * Get full subscription details including billing period and auto-renewal status
 */
export async function getSubscriptionDetailsAction(): Promise<SubscriptionActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return { success: false, error: 'Unauthorized' };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
      select: {
        subscriptionTier: true,
        subscriptionStatus: true,
        stripeSubscriptionId: true,
        stripePriceId: true,
        stripeCurrentPeriodEnd: true,
        stripeCustomerId: true,
      },
    });

    if (!user) {
      return { success: false, error: 'User not found' };
    }

    let billingPeriod: 'monthly' | 'yearly' | null = null;
    let autoRenewal = false;
    let currentPeriodEnd: string | null = null;
    let stripeStatus: string | null = null;

    if (user.stripeSubscriptionId) {
      try {
        const subscription = await stripe.subscriptions.retrieve(user.stripeSubscriptionId, {
          expand: ['items.data.price'],
        });
        autoRenewal = !subscription.cancel_at_period_end;
        stripeStatus = subscription.status;

        const periodEndDate = getSubscriptionPeriodEnd(subscription);
        currentPeriodEnd = periodEndDate?.toISOString() ?? null;

        // Determine billing period from actual Stripe price interval
        const price = subscription.items.data[0]?.price as any;
        if (price?.recurring?.interval) {
          billingPeriod = price.recurring.interval === 'year' ? 'yearly' : 'monthly';
        }
      } catch (error) {
        logger.error('Failed to retrieve Stripe subscription:', error);
      }
    }

    // Fall back to DB period end if Stripe retrieval didn't produce one
    if (!currentPeriodEnd && user.stripeCurrentPeriodEnd) {
      currentPeriodEnd = user.stripeCurrentPeriodEnd.toISOString();
    }

    return {
      success: true,
      data: {
        subscriptionTier: user.subscriptionTier,
        subscriptionStatus: user.subscriptionStatus,
        stripeStatus,
        billingPeriod,
        autoRenewal,
        currentPeriodEnd,
        hasStripeCustomer: !!user.stripeCustomerId,
      },
    };
  } catch (error: any) {
    logger.error('Get subscription details error:', error);
    return { success: false, error: error.message || 'Failed to get subscription details' };
  }
}

/**
 * Get saved payment methods for the customer
 */
export async function getPaymentMethodsAction(): Promise<SubscriptionActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return { success: false, error: 'Unauthorized' };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
      select: { stripeCustomerId: true },
    });

    if (!user || !user.stripeCustomerId) {
      return { success: true, data: { paymentMethods: [], defaultPaymentMethodId: null } };
    }

    // Get customer to find default payment method
    const customer = await stripe.customers.retrieve(user.stripeCustomerId);
    const defaultPaymentMethodId =
      !customer.deleted && customer.invoice_settings?.default_payment_method
        ? typeof customer.invoice_settings.default_payment_method === 'string'
          ? customer.invoice_settings.default_payment_method
          : customer.invoice_settings.default_payment_method.id
        : null;

    // List payment methods
    const paymentMethods = await stripe.paymentMethods.list({
      customer: user.stripeCustomerId,
      type: 'card',
    });

    const formatted = paymentMethods.data.map((pm) => ({
      id: pm.id,
      brand: pm.card?.brand || 'unknown',
      last4: pm.card?.last4 || '****',
      expMonth: pm.card?.exp_month || 0,
      expYear: pm.card?.exp_year || 0,
      isDefault: pm.id === defaultPaymentMethodId,
    }));

    return {
      success: true,
      data: { paymentMethods: formatted, defaultPaymentMethodId },
    };
  } catch (error: any) {
    logger.error('Get payment methods error:', error);
    return { success: false, error: error.message || 'Failed to get payment methods' };
  }
}

/**
 * Delete a saved payment method.
 * Blocked if auto-renewal is active on the subscription.
 */
export async function deletePaymentMethodAction(
  paymentMethodId: string
): Promise<SubscriptionActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return { success: false, error: 'Unauthorized' };
    }

    if (!paymentMethodId || typeof paymentMethodId !== 'string') {
      return { success: false, error: 'Invalid payment method ID' };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
      select: { stripeCustomerId: true, stripeSubscriptionId: true },
    });

    if (!user || !user.stripeCustomerId) {
      return { success: false, error: 'No billing information found' };
    }

    // Check if auto-renewal is active - block deletion if so
    if (user.stripeSubscriptionId) {
      const subscription = await stripe.subscriptions.retrieve(user.stripeSubscriptionId);
      if (!subscription.cancel_at_period_end && subscription.status === 'active') {
        return {
          success: false,
          error:
            'Cannot delete payment method while auto-renewal is active. Turn off auto-renewal first.',
        };
      }
    }

    // Verify the payment method belongs to this customer
    const pm = await stripe.paymentMethods.retrieve(paymentMethodId);
    const pmCustomerId = extractCustomerId(pm.customer as any);

    if (!pmCustomerId) {
      return { success: false, error: 'Payment method is not attached to any customer' };
    }

    if (pmCustomerId !== user.stripeCustomerId) {
      return {
        success: false,
        error: 'Payment method not found or does not belong to your account',
      };
    }

    await stripe.paymentMethods.detach(paymentMethodId);

    return { success: true, data: { message: 'Payment method removed' } };
  } catch (error: any) {
    logger.error('Delete payment method error:', error);
    return { success: false, error: error.message || 'Failed to delete payment method' };
  }
}

/**
 * Set a payment method as the default for the customer
 */
export async function setDefaultPaymentMethodAction(
  paymentMethodId: string
): Promise<SubscriptionActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return { success: false, error: 'Unauthorized' };
    }

    if (!paymentMethodId || typeof paymentMethodId !== 'string') {
      return { success: false, error: 'Invalid payment method ID' };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
      select: { stripeCustomerId: true, stripeSubscriptionId: true },
    });

    if (!user || !user.stripeCustomerId) {
      return { success: false, error: 'No billing information found' };
    }

    // Verify the payment method belongs to this customer
    const pm = await stripe.paymentMethods.retrieve(paymentMethodId);
    const pmCustomerId = extractCustomerId(pm.customer as any);

    // If payment method is not attached to a customer, attach it first
    if (!pm.customer) {
      await stripe.paymentMethods.attach(paymentMethodId, {
        customer: user.stripeCustomerId,
      });
    } else if (pmCustomerId !== user.stripeCustomerId) {
      return { success: false, error: 'Payment method does not belong to your account' };
    }

    // Set as default on customer
    await stripe.customers.update(user.stripeCustomerId, {
      invoice_settings: { default_payment_method: paymentMethodId },
    });

    // Also update on subscription if exists
    if (user.stripeSubscriptionId) {
      try {
        await stripe.subscriptions.update(user.stripeSubscriptionId, {
          default_payment_method: paymentMethodId,
        });
      } catch (subError) {
        // Subscription update may fail if subscription is in certain states;
        // customer-level default is already set so this is non-critical
        logger.error('Failed to update subscription default payment method:', subError);
      }
    }

    return { success: true, data: { message: 'Default payment method updated' } };
  } catch (error: any) {
    logger.error('Set default payment method error:', error);
    return { success: false, error: error.message || 'Failed to set default payment method' };
  }
}
