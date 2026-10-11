/**
 * Stripe Subscription Management
 *
 * Handles subscription creation, updates, cancellation, and synchronization
 */

import Stripe from 'stripe';
import { db } from '@/lib/db/client';

let stripeInstance: Stripe | null = null;

/**
 * Get or create Stripe client instance (lazy initialization)
 */
function getStripeClient(): Stripe {
  if (!process.env.STRIPE_SECRET_KEY) {
    throw new Error('STRIPE_SECRET_KEY is not defined. Please add it to your .env file.');
  }

  if (!stripeInstance) {
    stripeInstance = new Stripe(process.env.STRIPE_SECRET_KEY, {
      apiVersion: '2025-08-27.basil',
      typescript: true,
    });
  }

  return stripeInstance;
}

export interface CreateSubscriptionParams {
  userId: string;
  priceId: string;
  email: string;
}

export interface UpdateSubscriptionParams {
  userId: string;
  newPriceId: string;
}

/**
 * Create a Stripe customer and checkout session
 */
export async function createCheckoutSession(
  params: CreateSubscriptionParams
): Promise<Stripe.Checkout.Session> {
  const { userId, priceId, email } = params;

  // Get or create Stripe customer
  let stripeCustomerId: string;

  const user = await db.user.findUnique({
    where: { id: userId },
    select: { stripeCustomerId: true },
  });

  if (user?.stripeCustomerId) {
    stripeCustomerId = user.stripeCustomerId;
  } else {
    // Create new Stripe customer
    const customer = await getStripeClient().customers.create({
      email,
      metadata: { userId },
    });

    stripeCustomerId = customer.id;

    // Update user with Stripe customer ID
    await db.user.update({
      where: { id: userId },
      data: { stripeCustomerId },
    });
  }

  // Create checkout session
  const session = await getStripeClient().checkout.sessions.create({
    customer: stripeCustomerId,
    mode: 'subscription',
    payment_method_types: ['card'],
    line_items: [
      {
        price: priceId,
        quantity: 1,
      },
    ],
    success_url: `${process.env.NEXT_PUBLIC_APP_URL}/dashboard?success=true&session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${process.env.NEXT_PUBLIC_APP_URL}/pricing?canceled=true`,
    metadata: {
      userId,
    },
  });

  return session;
}

/**
 * Create a billing portal session for managing subscriptions
 */
export async function createBillingPortalSession(
  userId: string
): Promise<Stripe.BillingPortal.Session> {
  const user = await db.user.findUnique({
    where: { id: userId },
    select: { stripeCustomerId: true },
  });

  if (!user?.stripeCustomerId) {
    throw new Error('No Stripe customer found for user');
  }

  const session = await getStripeClient().billingPortal.sessions.create({
    customer: user.stripeCustomerId,
    return_url: `${process.env.NEXT_PUBLIC_APP_URL}/dashboard/settings/billing`,
  });

  return session;
}

/**
 * Update subscription to a new price/plan
 */
export async function updateSubscription(
  params: UpdateSubscriptionParams
): Promise<Stripe.Subscription> {
  const { userId, newPriceId } = params;

  const user = await db.user.findUnique({
    where: { id: userId },
    select: { stripeSubscriptionId: true },
  });

  if (!user?.stripeSubscriptionId) {
    throw new Error('No active subscription found');
  }

  // Get current subscription
  const subscription = await getStripeClient().subscriptions.retrieve(user.stripeSubscriptionId);

  // Update subscription with new price
  const updatedSubscription = await getStripeClient().subscriptions.update(
    user.stripeSubscriptionId,
    {
      items: [
        {
          id: subscription.items.data[0].id,
          price: newPriceId,
        },
      ],
      proration_behavior: 'create_prorations',
    }
  );

  // Update database
  await db.user.update({
    where: { id: userId },
    data: {
      stripePriceId: newPriceId,
      subscriptionTier: getSubscriptionTier(newPriceId),
    },
  });

  return updatedSubscription;
}

/**
 * Cancel subscription
 */
export async function cancelSubscription(
  userId: string,
  immediately = false
): Promise<Stripe.Subscription> {
  const user = await db.user.findUnique({
    where: { id: userId },
    select: { stripeSubscriptionId: true },
  });

  if (!user?.stripeSubscriptionId) {
    throw new Error('No active subscription found');
  }

  let subscription: Stripe.Subscription;

  if (immediately) {
    // Cancel immediately
    subscription = await getStripeClient().subscriptions.cancel(user.stripeSubscriptionId);

    // Update database
    await db.user.update({
      where: { id: userId },
      data: {
        subscriptionStatus: 'canceled',
        stripeCurrentPeriodEnd: null,
      },
    });
  } else {
    // Cancel at period end
    subscription = await getStripeClient().subscriptions.update(user.stripeSubscriptionId, {
      cancel_at_period_end: true,
    });

    // Update database
    await db.user.update({
      where: { id: userId },
      data: {
        subscriptionStatus: 'canceling',
      },
    });
  }

  return subscription;
}

/**
 * Resume a canceled subscription
 */
export async function resumeSubscription(userId: string): Promise<Stripe.Subscription> {
  const user = await db.user.findUnique({
    where: { id: userId },
    select: { stripeSubscriptionId: true },
  });

  if (!user?.stripeSubscriptionId) {
    throw new Error('No subscription found');
  }

  const subscription = await getStripeClient().subscriptions.update(user.stripeSubscriptionId, {
    cancel_at_period_end: false,
  });

  // Update database
  await db.user.update({
    where: { id: userId },
    data: {
      subscriptionStatus: 'active',
    },
  });

  return subscription;
}

/**
 * Get subscription details
 */
export async function getSubscription(userId: string): Promise<Stripe.Subscription | null> {
  const user = await db.user.findUnique({
    where: { id: userId },
    select: { stripeSubscriptionId: true },
  });

  if (!user?.stripeSubscriptionId) {
    return null;
  }

  return getStripeClient().subscriptions.retrieve(user.stripeSubscriptionId);
}

/**
 * Get subscription tier from price ID
 */
export function getSubscriptionTier(priceId: string): string {
  // Check Pro tier (monthly and yearly)
  if (
    priceId === process.env.STRIPE_PRICE_ID_PRO ||
    priceId === process.env.STRIPE_PRICE_ID_PRO_MONTHLY ||
    priceId === process.env.STRIPE_PRICE_ID_PRO_YEARLY
  ) {
    return 'pro';
  }

  // Check Enterprise tier (monthly and yearly)
  if (
    priceId === process.env.STRIPE_PRICE_ID_ENTERPRISE ||
    priceId === process.env.STRIPE_PRICE_ID_ENTERPRISE_MONTHLY ||
    priceId === process.env.STRIPE_PRICE_ID_ENTERPRISE_YEARLY
  ) {
    return 'enterprise';
  }

  // Check Free tier
  if (priceId === process.env.STRIPE_PRICE_ID_FREE) {
    return 'free';
  }

  // Default to free if price ID doesn't match any known tier
  return 'free';
}

/**
 * Sync subscription status from Stripe
 */
export async function syncSubscriptionStatus(userId: string): Promise<void> {
  const subscription = await getSubscription(userId);

  if (!subscription) {
    await db.user.update({
      where: { id: userId },
      data: {
        subscriptionStatus: 'inactive',
        subscriptionTier: 'free',
      },
    });
    return;
  }

  const priceId = subscription.items.data[0]?.price.id;

  await db.user.update({
    where: { id: userId },
    data: {
      subscriptionStatus: subscription.status,
      stripePriceId: priceId,
      subscriptionTier: getSubscriptionTier(priceId || ''),
      stripeCurrentPeriodEnd: new Date((subscription as any).current_period_end * 1000),
    },
  });
}

export { getStripeClient as stripe };
