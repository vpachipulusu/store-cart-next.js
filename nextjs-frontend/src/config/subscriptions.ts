import { fetchPlanPrices, type PlanPrices } from '@/lib/api/plan-prices';
import { fetchPlatformCurrency } from '@/lib/api/settings';
import { logger } from '@/lib/logger';
import { CURRENCIES } from './currencies';

export const SUBSCRIPTION_TIERS = {
  FREE: 'free',
  PRO: 'pro',
  ENTERPRISE: 'enterprise',
} as const;

export type SubscriptionTier = (typeof SUBSCRIPTION_TIERS)[keyof typeof SUBSCRIPTION_TIERS];

export interface SubscriptionPlan {
  name: string;
  description: string;
  features: string[];
  price: {
    monthly: number;
    yearly: number;
  };
  tier: SubscriptionTier;
  popular?: boolean;
}

export type StripePrices = PlanPrices;

export const subscriptionPlans: SubscriptionPlan[] = [
  {
    name: 'Free',
    description:
      'Perfect for getting started. Features below are placeholders, not included or enforced.',
    features: [
      'Example: Up to 3 projects',
      'Example: Basic analytics',
      'Example: Community support',
      'Example: 1 GB storage',
    ],
    price: {
      monthly: 0,
      yearly: 0,
    },
    tier: SUBSCRIPTION_TIERS.FREE,
  },
  {
    name: 'Pro',
    description:
      'For professionals and growing teams. Features below are placeholders, not included or enforced.',
    features: [
      'Example: Unlimited projects',
      'Example: Advanced analytics',
      'Example: Priority support',
      'Example: 50 GB storage',
      'Example: Custom domains',
      'Example: API access',
    ],
    price: {
      monthly: 0, // Resolved at runtime via getStripePrices()
      yearly: 0,
    },
    tier: SUBSCRIPTION_TIERS.PRO,
    popular: true,
  },
  {
    name: 'Enterprise',
    description:
      'For large organizations. Features below are placeholders, not included or enforced.',
    features: [
      'Example: Everything in Pro',
      'Example: Dedicated account manager',
      'Example: 24/7 phone support',
      'Example: Unlimited storage',
      'Example: Advanced security',
      'Example: SLA guarantee',
      'Example: Custom integrations',
    ],
    price: {
      monthly: 0, // Resolved at runtime via getStripePrices()
      yearly: 0,
    },
    tier: SUBSCRIPTION_TIERS.ENTERPRISE,
  },
];

/**
 * Plan prices from the backend (`GET /v1/settings/plan-prices`), cached for one hour per server instance.
 * A price the backend cannot read is 0; a failed read is all zeros.
 */
export const getStripePrices = fetchPlanPrices;

/**
 * Returns subscription plans with prices read through the backend.
 */
export async function getSubscriptionPlans(): Promise<SubscriptionPlan[]> {
  const prices = await getStripePrices();

  return subscriptionPlans.map((plan) => {
    if (plan.tier === 'pro') {
      return { ...plan, price: prices.pro };
    }
    if (plan.tier === 'enterprise') {
      return { ...plan, price: prices.enterprise };
    }
    return plan;
  });
}

export { CURRENCIES };

/**
 * Currency symbol of the platform currency, read from the backend. Any failure is logged and answered with
 * '$'. The read is cached in `fetchPlatformCurrency`.
 */
export async function getCurrencySymbol(): Promise<string> {
  try {
    const code = await fetchPlatformCurrency();
    return CURRENCIES.find((c) => c.code === code)?.symbol ?? '$';
  } catch (error) {
    logger.error('Failed to fetch currency symbol:', error);
    return '$';
  }
}
