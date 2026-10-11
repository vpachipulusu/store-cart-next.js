import { unstable_cache } from 'next/cache';
import Stripe from 'stripe';
import { db } from '@/lib/db/client';
import { logger } from '@/lib/logger';

export const SUBSCRIPTION_TIERS = {
  FREE: 'free',
  PRO: 'pro',
  ENTERPRISE: 'enterprise',
} as const;

export type SubscriptionTier = typeof SUBSCRIPTION_TIERS[keyof typeof SUBSCRIPTION_TIERS];

export interface SubscriptionPlan {
  name: string;
  description: string;
  features: string[];
  price: {
    monthly: number;
    yearly: number;
  };
  stripePriceId: {
    monthly: string;
    yearly: string;
  };
  tier: SubscriptionTier;
  popular?: boolean;
}

export interface StripePrices {
  pro: { monthly: number; yearly: number };
  enterprise: { monthly: number; yearly: number };
}

const FALLBACK_PRICES: StripePrices = {
  pro: { monthly: 0, yearly: 0 },
  enterprise: { monthly: 0, yearly: 0 },
};

export const subscriptionPlans: SubscriptionPlan[] = [
  {
    name: 'Free',
    description: 'Perfect for getting started',
    features: [
      'Up to 3 projects',
      'Basic analytics',
      'Community support',
      '1 GB storage',
    ],
    price: {
      monthly: 0,
      yearly: 0,
    },
    stripePriceId: {
      monthly: '',
      yearly: '',
    },
    tier: SUBSCRIPTION_TIERS.FREE,
  },
  {
    name: 'Pro',
    description: 'For professionals and growing teams',
    features: [
      'Unlimited projects',
      'Advanced analytics',
      'Priority support',
      '50 GB storage',
      'Custom domains',
      'API access',
    ],
    price: {
      monthly: 0, // Resolved at runtime via getStripePrices()
      yearly: 0,
    },
    stripePriceId: {
      monthly: process.env.STRIPE_PRICE_ID_PRO_MONTHLY || '',
      yearly: process.env.STRIPE_PRICE_ID_PRO_YEARLY || '',
    },
    tier: SUBSCRIPTION_TIERS.PRO,
    popular: true,
  },
  {
    name: 'Enterprise',
    description: 'For large organizations',
    features: [
      'Everything in Pro',
      'Dedicated account manager',
      '24/7 phone support',
      'Unlimited storage',
      'Advanced security',
      'SLA guarantee',
      'Custom integrations',
    ],
    price: {
      monthly: 0, // Resolved at runtime via getStripePrices()
      yearly: 0,
    },
    stripePriceId: {
      monthly: process.env.STRIPE_PRICE_ID_ENTERPRISE_MONTHLY || '',
      yearly: process.env.STRIPE_PRICE_ID_ENTERPRISE_YEARLY || '',
    },
    tier: SUBSCRIPTION_TIERS.ENTERPRISE,
  },
];

async function fetchStripePrices(): Promise<StripePrices> {
  try {
    if (!process.env.STRIPE_SECRET_KEY) {
      logger.warn('STRIPE_SECRET_KEY not set, using fallback prices');
      return FALLBACK_PRICES;
    }

    const stripe = new Stripe(process.env.STRIPE_SECRET_KEY, {
      apiVersion: '2025-08-27.basil',
      typescript: true,
    });

    const priceIds = [
      process.env.STRIPE_PRICE_ID_PRO_MONTHLY,
      process.env.STRIPE_PRICE_ID_PRO_YEARLY,
      process.env.STRIPE_PRICE_ID_ENTERPRISE_MONTHLY,
      process.env.STRIPE_PRICE_ID_ENTERPRISE_YEARLY,
    ].filter(Boolean) as string[];

    if (priceIds.length === 0) {
      logger.warn('No Stripe price IDs configured, using fallback prices');
      return FALLBACK_PRICES;
    }

    const prices = await Promise.all(
      priceIds.map((id) => stripe.prices.retrieve(id))
    );

    const priceMap = new Map<string, number>();
    for (const price of prices) {
      priceMap.set(price.id, (price.unit_amount ?? 0) / 100);
    }

    return {
      pro: {
        monthly: priceMap.get(process.env.STRIPE_PRICE_ID_PRO_MONTHLY || '') ?? 0,
        yearly: priceMap.get(process.env.STRIPE_PRICE_ID_PRO_YEARLY || '') ?? 0,
      },
      enterprise: {
        monthly: priceMap.get(process.env.STRIPE_PRICE_ID_ENTERPRISE_MONTHLY || '') ?? 0,
        yearly: priceMap.get(process.env.STRIPE_PRICE_ID_ENTERPRISE_YEARLY || '') ?? 0,
      },
    };
  } catch (error) {
    logger.error('Failed to fetch Stripe prices:', error);
    return FALLBACK_PRICES;
  }
}

/**
 * Cached Stripe prices. Revalidates every 1 hour.
 */
export const getStripePrices = unstable_cache(
  fetchStripePrices,
  ['stripe-prices'],
  { revalidate: 3600, tags: ['stripe-prices'] }
);

/**
 * Returns subscription plans with prices fetched from Stripe.
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

/**
 * Supported currencies with their symbols.
 */
export const CURRENCIES = [
  { code: 'USD', symbol: '$', name: 'US Dollar' },
  { code: 'EUR', symbol: '€', name: 'Euro' },
  { code: 'GBP', symbol: '£', name: 'British Pound' },
  { code: 'JPY', symbol: '¥', name: 'Japanese Yen' },
  { code: 'AUD', symbol: 'A$', name: 'Australian Dollar' },
  { code: 'CAD', symbol: 'C$', name: 'Canadian Dollar' },
  { code: 'CHF', symbol: 'Fr', name: 'Swiss Franc' },
  { code: 'CNY', symbol: '¥', name: 'Chinese Yuan' },
  { code: 'INR', symbol: '₹', name: 'Indian Rupee' },
] as const;

async function fetchCurrencySymbol(): Promise<string> {
  try {
    const setting = await db.appSettings.findUnique({
      where: { key: 'currency' },
    });

    const code = (setting?.value as string) || 'USD';
    return CURRENCIES.find((c) => c.code === code)?.symbol ?? '$';
  } catch (error) {
    return '$';
  }
}

/**
 * Cached currency symbol from admin settings. Revalidates every 1 hour.
 */
export const getCurrencySymbol = unstable_cache(
  fetchCurrencySymbol,
  ['currency-symbol'],
  { revalidate: 3600, tags: ['currency-setting'] }
);
