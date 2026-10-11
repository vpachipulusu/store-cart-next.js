/**
 * Stripe Webhook Handlers
 *
 * Handles all Stripe webhook events
 */

import Stripe from 'stripe';
import { revalidatePath } from 'next/cache';
import { db } from '@/lib/db/client';
import { getSubscriptionTier } from './subscriptions';
import { notifySubscriptionChanged, notifyPaymentFailed } from '@/lib/utils/notifications';
import { logger } from '@/lib/logger';

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

/**
 * Verify webhook signature
 */
export function verifyWebhookSignature(payload: string | Buffer, signature: string): Stripe.Event {
  if (!process.env.STRIPE_WEBHOOK_SECRET) {
    throw new Error('STRIPE_WEBHOOK_SECRET is not defined');
  }

  return getStripeClient().webhooks.constructEvent(
    payload,
    signature,
    process.env.STRIPE_WEBHOOK_SECRET
  );
}

/**
 * Handle checkout session completed
 */
async function handleCheckoutSessionCompleted(session: Stripe.Checkout.Session): Promise<void> {
  logger.info('Processing checkout.session.completed event:', session.id);

  const userId = session.metadata?.userId;

  if (!userId) {
    logger.error('No userId in session metadata', { sessionId: session.id });
    return;
  }

  const subscriptionId = session.subscription as string;

  if (!subscriptionId) {
    logger.error('No subscription ID in session', { sessionId: session.id, userId });
    return;
  }

  logger.info('Retrieving subscription details:', { userId, subscriptionId });

  // Retrieve subscription details
  const subscription = await getStripeClient().subscriptions.retrieve(subscriptionId);
  const priceId = subscription.items.data[0]?.price.id;
  const tier = getSubscriptionTier(priceId || '');

  logger.info('Subscription details:', {
    userId,
    subscriptionId,
    priceId,
    tier,
    status: subscription.status,
  });

  // Update user in database
  await db.user.update({
    where: { id: userId },
    data: {
      stripeCustomerId: session.customer as string,
      stripeSubscriptionId: subscriptionId,
      stripePriceId: priceId,
      subscriptionTier: tier,
      subscriptionStatus: subscription.status,
      stripeCurrentPeriodEnd: new Date((subscription as any).current_period_end * 1000),
    },
  });

  logger.info('User subscription updated successfully:', { userId, tier });

  // Create audit log
  await db.auditLog.create({
    data: {
      userId,
      action: 'subscription.created',
      resource: 'Subscription',
      resourceId: subscriptionId,
      metadata: {
        priceId,
        tier,
      },
    },
  });

  // Revalidate admin and dashboard pages to show updated subscription
  try {
    revalidatePath('/admin/subscriptions');
    revalidatePath('/dashboard');
    logger.info('Revalidated admin and dashboard pages');
  } catch (error) {
    logger.error('Error revalidating paths:', error);
  }

  logger.info(`Subscription created for user ${userId} with tier ${tier}`);
}

/**
 * Handle subscription updated
 */
async function handleSubscriptionUpdated(subscription: Stripe.Subscription): Promise<void> {
  const userId = subscription.metadata?.userId;

  // Find user by Stripe customer ID if userId not in metadata
  const user = userId
    ? await db.user.findUnique({ where: { id: userId } })
    : await db.user.findUnique({
        where: { stripeCustomerId: subscription.customer as string },
      });

  if (!user) {
    logger.error('User not found for subscription update');
    return;
  }

  const priceId = subscription.items.data[0]?.price.id;

  // Update user subscription
  await db.user.update({
    where: { id: user.id },
    data: {
      stripePriceId: priceId,
      subscriptionTier: getSubscriptionTier(priceId || ''),
      subscriptionStatus: subscription.status,
      stripeCurrentPeriodEnd: new Date((subscription as any).current_period_end * 1000),
    },
  });

  // Create audit log
  await db.auditLog.create({
    data: {
      userId: user.id,
      action: 'subscription.updated',
      resource: 'Subscription',
      resourceId: subscription.id,
      metadata: {
        priceId,
        tier: getSubscriptionTier(priceId || ''),
        status: subscription.status,
      },
    },
  });

  // Notify user about subscription change
  await notifySubscriptionChanged(user.id, getSubscriptionTier(priceId || ''));

  // Revalidate pages
  try {
    revalidatePath('/admin/subscriptions');
    revalidatePath('/dashboard');
  } catch (error) {
    logger.error('Error revalidating paths:', error);
  }

  logger.info(`Subscription updated for user ${user.id}`);
}

/**
 * Handle subscription deleted/canceled
 */
async function handleSubscriptionDeleted(subscription: Stripe.Subscription): Promise<void> {
  const user = await db.user.findUnique({
    where: { stripeCustomerId: subscription.customer as string },
  });

  if (!user) {
    logger.error('User not found for subscription deletion');
    return;
  }

  // Update user to free tier
  await db.user.update({
    where: { id: user.id },
    data: {
      stripePriceId: null,
      subscriptionTier: 'free',
      subscriptionStatus: 'canceled',
      stripeCurrentPeriodEnd: null,
    },
  });

  // Create audit log
  await db.auditLog.create({
    data: {
      userId: user.id,
      action: 'subscription.deleted',
      resource: 'Subscription',
      resourceId: subscription.id,
      metadata: {
        cancellationReason: subscription.cancellation_details?.reason,
      },
    },
  });

  // Notify user about subscription cancellation
  await notifySubscriptionChanged(user.id, 'free');

  // Revalidate pages
  try {
    revalidatePath('/admin/subscriptions');
    revalidatePath('/dashboard');
  } catch (error) {
    logger.error('Error revalidating paths:', error);
  }

  logger.info(`Subscription canceled for user ${user.id}`);
}

/**
 * Handle invoice payment succeeded
 */
async function handleInvoicePaymentSucceeded(invoice: Stripe.Invoice): Promise<void> {
  const subscriptionId = (invoice as any).subscription as string;

  if (!subscriptionId) {
    return; // Not a subscription invoice
  }

  const user = await db.user.findUnique({
    where: { stripeSubscriptionId: subscriptionId },
  });

  if (!user) {
    logger.error('User not found for invoice payment');
    return;
  }

  // Retrieve subscription to get current period end
  const subscription = await getStripeClient().subscriptions.retrieve(subscriptionId);

  // Update user with new period end
  await db.user.update({
    where: { id: user.id },
    data: {
      subscriptionStatus: 'active',
      stripeCurrentPeriodEnd: new Date((subscription as any).current_period_end * 1000),
    },
  });

  // Create audit log
  await db.auditLog.create({
    data: {
      userId: user.id,
      action: 'invoice.payment_succeeded',
      resource: 'Invoice',
      resourceId: invoice.id,
      metadata: {
        amount: invoice.amount_paid,
        currency: invoice.currency,
      },
    },
  });

  logger.info(`Invoice payment succeeded for user ${user.id}`);
}

/**
 * Handle invoice payment failed
 */
async function handleInvoicePaymentFailed(invoice: Stripe.Invoice): Promise<void> {
  const subscriptionId = (invoice as any).subscription as string;

  if (!subscriptionId) {
    return;
  }

  const user = await db.user.findUnique({
    where: { stripeSubscriptionId: subscriptionId },
  });

  if (!user) {
    logger.error('User not found for invoice payment failure');
    return;
  }

  // Update subscription status
  await db.user.update({
    where: { id: user.id },
    data: {
      subscriptionStatus: 'past_due',
    },
  });

  // Create audit log
  await db.auditLog.create({
    data: {
      userId: user.id,
      action: 'invoice.payment_failed',
      resource: 'Invoice',
      resourceId: invoice.id,
      metadata: {
        amount: invoice.amount_due,
        currency: invoice.currency,
      },
    },
  });

  // Create notification for user
  await db.notification.create({
    data: {
      userId: user.id,
      type: 'payment_failed',
      title: 'Payment Failed',
      message: 'Your subscription payment has failed. Please update your payment method.',
      link: '/dashboard/settings/billing',
    },
  });

  logger.info(`Invoice payment failed for user ${user.id}`);
}

/**
 * Handle customer subscription trial will end
 */
async function handleCustomerSubscriptionTrialWillEnd(
  subscription: Stripe.Subscription
): Promise<void> {
  const user = await db.user.findUnique({
    where: { stripeCustomerId: subscription.customer as string },
  });

  if (!user) {
    logger.error('User not found for trial ending notification');
    return;
  }

  // Create notification
  await db.notification.create({
    data: {
      userId: user.id,
      type: 'trial_ending',
      title: 'Trial Ending Soon',
      message: 'Your trial period is ending soon. Update your payment method to continue.',
      link: '/dashboard/settings/billing',
    },
  });

  logger.info(`Trial ending notification sent to user ${user.id}`);
}

/**
 * Main webhook event handler
 */
export async function handleWebhookEvent(event: Stripe.Event): Promise<void> {
  try {
    switch (event.type) {
      case 'checkout.session.completed':
        await handleCheckoutSessionCompleted(event.data.object as Stripe.Checkout.Session);
        break;

      case 'customer.subscription.created':
      case 'customer.subscription.updated':
        await handleSubscriptionUpdated(event.data.object as Stripe.Subscription);
        break;

      case 'customer.subscription.deleted':
        await handleSubscriptionDeleted(event.data.object as Stripe.Subscription);
        break;

      case 'invoice.payment_succeeded':
        await handleInvoicePaymentSucceeded(event.data.object as Stripe.Invoice);
        break;

      case 'invoice.payment_failed':
        await handleInvoicePaymentFailed(event.data.object as Stripe.Invoice);
        break;

      case 'customer.subscription.trial_will_end':
        await handleCustomerSubscriptionTrialWillEnd(event.data.object as Stripe.Subscription);
        break;

      default:
        logger.info(`Unhandled event type: ${event.type}`);
    }
  } catch (error) {
    logger.error(`Error handling webhook event ${event.type}:`, error);
    throw error;
  }
}

const stripe = getStripeClient();
export { stripe };
