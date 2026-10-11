'use server';

import { cookies } from 'next/headers';
import { z } from 'zod';
import Stripe from 'stripe';
import { adminAuth } from '@/lib/firebase/admin';
import { db } from '@/lib/db/client';
import { logger } from '@/lib/logger';

/**
 * Initialize Stripe
 */
const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: '2025-08-27.basil',
  typescript: true,
});

/**
 * Response type for admin subscription actions
 */
type AdminSubscriptionActionResponse<T = any> = {
  success: boolean;
  data?: T;
  error?: string;
};

/**
 * Get authenticated admin user
 */
async function getAuthenticatedAdmin() {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get('session')?.value;

    if (!sessionCookie) {
      return null;
    }

    const decodedClaims = await adminAuth.verifySessionCookie(sessionCookie, true);
    const user = await db.user.findUnique({
      where: { firebaseUid: decodedClaims.uid },
      include: {
        adminUser: true,
      },
    });

    if (!user || !user.adminUser) {
      return null;
    }

    return user;
  } catch (error) {
    logger.error('Admin authentication error:', error);
    return null;
  }
}

/**
 * Check if user has admin permission
 */
function hasPermission(admin: any, permission: string): boolean {
  const permissions = (admin.adminUser?.permissions as string[]) || [];
  return permissions.includes(permission) || permissions.includes('*');
}

/**
 * Get all subscriptions with filters
 */
export async function getAllSubscriptionsAction(
  page = 1,
  limit = 20,
  filters?: {
    status?: string;
    tier?: string;
  }
): Promise<AdminSubscriptionActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'subscriptions.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Build where clause
    const where: any = {};

    if (filters?.status) {
      where.subscriptionStatus = filters.status;
    }

    if (filters?.tier) {
      where.subscriptionTier = filters.tier;
    }

    // Only get users with subscriptions
    where.stripeSubscriptionId = { not: null };

    // Get subscriptions with pagination
    const [users, totalCount] = await Promise.all([
      db.user.findMany({
        where,
        select: {
          id: true,
          email: true,
          displayName: true,
          subscriptionTier: true,
          subscriptionStatus: true,
          stripeSubscriptionId: true,
          stripePriceId: true,
          stripeCurrentPeriodEnd: true,
          createdAt: true,
        },
        orderBy: { createdAt: 'desc' },
        take: limit,
        skip: (page - 1) * limit,
      }),
      db.user.count({ where }),
    ]);

    return {
      success: true,
      data: {
        subscriptions: users,
        pagination: {
          page,
          limit,
          totalCount,
          totalPages: Math.ceil(totalCount / limit),
        },
      },
    };
  } catch (error: any) {
    logger.error('Get all subscriptions error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get subscriptions',
    };
  }
}

/**
 * Get subscription statistics
 */
export async function getSubscriptionStatsAction(): Promise<AdminSubscriptionActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'subscriptions.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const [
      totalSubscriptions,
      activeSubscriptions,
      canceledSubscriptions,
      trialSubscriptions,
      subscriptionsByTier,
      monthlyRevenue,
    ] = await Promise.all([
      db.user.count({
        where: { stripeSubscriptionId: { not: null } },
      }),
      db.user.count({
        where: { subscriptionStatus: 'active' },
      }),
      db.user.count({
        where: { subscriptionStatus: 'canceled' },
      }),
      db.user.count({
        where: { subscriptionStatus: 'trialing' },
      }),
      db.user.groupBy({
        by: ['subscriptionTier'],
        where: { subscriptionStatus: 'active' },
        _count: true,
      }),
      // Note: This is a simplified calculation
      // In production, you'd calculate this from Stripe data
      db.user.count({
        where: {
          subscriptionStatus: 'active',
          subscriptionTier: { not: 'free' },
        },
      }),
    ]);

    return {
      success: true,
      data: {
        totalSubscriptions,
        activeSubscriptions,
        canceledSubscriptions,
        trialSubscriptions,
        subscriptionsByTier: subscriptionsByTier.reduce(
          (acc, item) => {
            acc[item.subscriptionTier] = item._count;
            return acc;
          },
          {} as Record<string, number>
        ),
        estimatedMonthlyRevenue: monthlyRevenue,
      },
    };
  } catch (error: any) {
    logger.error('Get subscription stats error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get subscription statistics',
    };
  }
}

/**
 * Get user subscription details
 */
export async function getUserSubscriptionDetailsAction(
  userId: string
): Promise<AdminSubscriptionActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'subscriptions.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
      select: {
        id: true,
        email: true,
        displayName: true,
        stripeCustomerId: true,
        stripeSubscriptionId: true,
        stripePriceId: true,
        subscriptionTier: true,
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

    let stripeSubscription = null;
    let stripeInvoices = null;

    // Get Stripe subscription details if exists
    if (user.stripeSubscriptionId) {
      try {
        stripeSubscription = await stripe.subscriptions.retrieve(user.stripeSubscriptionId);
      } catch (error) {
        logger.error('Failed to retrieve Stripe subscription:', error);
      }
    }

    // Get Stripe invoices if customer exists
    if (user.stripeCustomerId) {
      try {
        const invoices = await stripe.invoices.list({
          customer: user.stripeCustomerId,
          limit: 10,
        });
        stripeInvoices = invoices.data;
      } catch (error) {
        logger.error('Failed to retrieve Stripe invoices:', error);
      }
    }

    return {
      success: true,
      data: {
        user,
        stripeSubscription,
        stripeInvoices,
      },
    };
  } catch (error: any) {
    logger.error('Get user subscription details error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get subscription details',
    };
  }
}

/**
 * Update user subscription schema
 */
const updateSubscriptionSchema = z.object({
  subscriptionTier: z.string(),
  subscriptionStatus: z.string(),
});

/**
 * Manually update user subscription
 */
export async function updateUserSubscriptionAction(
  userId: string,
  data: z.infer<typeof updateSubscriptionSchema>
): Promise<AdminSubscriptionActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'subscriptions.update')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Validate input
    const validation = updateSubscriptionSchema.safeParse(data);
    if (!validation.success) {
      return {
        success: false,
        error: validation.error.errors[0].message,
      };
    }

    // Update user subscription
    const updatedUser = await db.user.update({
      where: { id: userId },
      data: {
        subscriptionTier: data.subscriptionTier,
        subscriptionStatus: data.subscriptionStatus,
      },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'subscription.updated',
        resource: 'User',
        resourceId: userId,
        metadata: {
          tier: data.subscriptionTier,
          status: data.subscriptionStatus,
        },
      },
    });

    return {
      success: true,
      data: { user: updatedUser },
    };
  } catch (error: any) {
    logger.error('Update user subscription error:', error);
    return {
      success: false,
      error: error.message || 'Failed to update subscription',
    };
  }
}

/**
 * Cancel user subscription
 */
export async function cancelUserSubscriptionAction(
  userId: string,
  immediately = false
): Promise<AdminSubscriptionActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'subscriptions.update')) {
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

    if (immediately) {
      // Cancel immediately
      await stripe.subscriptions.cancel(user.stripeSubscriptionId);

      // Update database
      await db.user.update({
        where: { id: userId },
        data: {
          subscriptionStatus: 'canceled',
          stripeSubscriptionId: null,
          stripePriceId: null,
        },
      });
    } else {
      // Cancel at period end
      await stripe.subscriptions.update(user.stripeSubscriptionId, {
        cancel_at_period_end: true,
      });
    }

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'subscription.canceled',
        resource: 'User',
        resourceId: userId,
        metadata: { immediately },
      },
    });

    return {
      success: true,
      data: {
        message: immediately
          ? 'Subscription canceled immediately'
          : 'Subscription will be canceled at period end',
      },
    };
  } catch (error: any) {
    logger.error('Cancel user subscription error:', error);
    return {
      success: false,
      error: error.message || 'Failed to cancel subscription',
    };
  }
}

/**
 * Refund subscription payment
 */
export async function refundSubscriptionPaymentAction(
  userId: string,
  amount?: number
): Promise<AdminSubscriptionActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'subscriptions.refund')) {
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

    // Get latest successful payment intent
    const charges = await stripe.charges.list({
      customer: user.stripeCustomerId,
      limit: 1,
    });

    if (charges.data.length === 0) {
      return {
        success: false,
        error: 'No charges found',
      };
    }

    const charge = charges.data[0];

    // Create refund
    const refund = await stripe.refunds.create({
      charge: charge.id,
      amount: amount, // If undefined, refunds full amount
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'subscription.refunded',
        resource: 'User',
        resourceId: userId,
        metadata: {
          refundId: refund.id,
          amount: refund.amount,
          chargeId: charge.id,
        },
      },
    });

    return {
      success: true,
      data: {
        message: 'Refund processed successfully',
        refund: {
          id: refund.id,
          amount: refund.amount,
          status: refund.status,
        },
      },
    };
  } catch (error: any) {
    logger.error('Refund subscription payment error:', error);
    return {
      success: false,
      error: error.message || 'Failed to process refund',
    };
  }
}

/**
 * Grant free subscription
 */
export async function grantFreeSubscriptionAction(
  userId: string,
  tier: string,
  durationInDays: number
): Promise<AdminSubscriptionActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'subscriptions.grant')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const endDate = new Date();
    endDate.setDate(endDate.getDate() + durationInDays);

    // Update user subscription
    const updatedUser = await db.user.update({
      where: { id: userId },
      data: {
        subscriptionTier: tier,
        subscriptionStatus: 'active',
        stripeCurrentPeriodEnd: endDate,
      },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'subscription.granted',
        resource: 'User',
        resourceId: userId,
        metadata: {
          tier,
          durationInDays,
          endDate,
        },
      },
    });

    return {
      success: true,
      data: {
        message: 'Free subscription granted successfully',
        user: updatedUser,
      },
    };
  } catch (error: any) {
    logger.error('Grant free subscription error:', error);
    return {
      success: false,
      error: error.message || 'Failed to grant subscription',
    };
  }
}

/**
 * Get subscription revenue analytics
 */
export async function getSubscriptionRevenueAction(
  startDate?: Date,
  endDate?: Date
): Promise<AdminSubscriptionActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'subscriptions.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Get all Stripe customers
    const users = await db.user.findMany({
      where: {
        stripeCustomerId: { not: null },
      },
      select: { stripeCustomerId: true },
    });

    const customerIds = users.map((u) => u.stripeCustomerId!);

    // Fetch revenue data from Stripe
    // Note: This is a simplified version. In production, you'd want to
    // use Stripe's reporting API or webhooks to track revenue
    let totalRevenue = 0;
    const revenueByMonth: Record<string, number> = {};

    for (const customerId of customerIds) {
      try {
        const invoices = await stripe.invoices.list({
          customer: customerId,
          status: 'paid',
          limit: 100,
        });

        invoices.data.forEach((invoice) => {
          const invoiceDate = new Date(invoice.created * 1000);

          if (startDate && invoiceDate < startDate) return;
          if (endDate && invoiceDate > endDate) return;

          totalRevenue += invoice.amount_paid;

          const monthKey = `${invoiceDate.getFullYear()}-${String(invoiceDate.getMonth() + 1).padStart(2, '0')}`;
          revenueByMonth[monthKey] = (revenueByMonth[monthKey] || 0) + invoice.amount_paid;
        });
      } catch (error) {
        logger.error(`Failed to fetch invoices for customer ${customerId}:`, error);
      }
    }

    return {
      success: true,
      data: {
        totalRevenue: totalRevenue / 100, // Convert from cents to dollars
        revenueByMonth: Object.entries(revenueByMonth).map(([month, amount]) => ({
          month,
          amount: amount / 100,
        })),
      },
    };
  } catch (error: any) {
    logger.error('Get subscription revenue error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get revenue data',
    };
  }
}

/**
 * Sync Stripe subscriptions with database
 */
export async function syncStripeSubscriptionsAction(): Promise<AdminSubscriptionActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'subscriptions.sync')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const users = await db.user.findMany({
      where: {
        stripeSubscriptionId: { not: null },
      },
    });

    let syncedCount = 0;
    let errorCount = 0;

    for (const user of users) {
      try {
        const subscription = await stripe.subscriptions.retrieve(user.stripeSubscriptionId!);

        await db.user.update({
          where: { id: user.id },
          data: {
            subscriptionStatus: subscription.status,
            stripePriceId: subscription.items.data[0].price.id,
            stripeCurrentPeriodEnd: new Date((subscription as any).current_period_end * 1000),
          },
        });

        syncedCount++;
      } catch (error) {
        logger.error(`Failed to sync subscription for user ${user.id}:`, error);
        errorCount++;
      }
    }

    return {
      success: true,
      data: {
        message: 'Stripe subscriptions synced',
        syncedCount,
        errorCount,
      },
    };
  } catch (error: any) {
    logger.error('Sync Stripe subscriptions error:', error);
    return {
      success: false,
      error: error.message || 'Failed to sync subscriptions',
    };
  }
}
