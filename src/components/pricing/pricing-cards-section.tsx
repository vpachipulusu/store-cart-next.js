'use client';

import { useState } from 'react';
import { BillingToggle } from '@/components/pricing/billing-toggle';
import { PricingCard } from '@/components/pricing/pricing-card';

interface TierData {
  name: string;
  monthlyPrice: number;
  yearlyPrice: number;
  description: string;
  features: string[];
  limitations: string[];
  cta: string;
  href: string;
  popular: boolean;
}

interface PricingCardsSectionProps {
  tiers: TierData[];
  currencySymbol: string;
  isAuthenticated: boolean;
  userTier?: string;
}

export function PricingCardsSection({
  tiers,
  currencySymbol,
  isAuthenticated,
  userTier,
}: PricingCardsSectionProps) {
  const [billingPeriod, setBillingPeriod] = useState<'monthly' | 'yearly'>('monthly');

  // Calculate savings percentage from the Pro tier prices
  const proTier = tiers.find((t) => t.name === 'Pro');
  const yearlySavingsPercent =
    proTier && proTier.monthlyPrice > 0 && proTier.yearlyPrice > 0
      ? Math.max(0, Math.round((1 - proTier.yearlyPrice / (proTier.monthlyPrice * 12)) * 100))
      : 0;

  return (
    <div className="mb-12 space-y-8">
      <BillingToggle
        billingPeriod={billingPeriod}
        onToggle={setBillingPeriod}
        yearlySavingsPercent={yearlySavingsPercent}
      />
      <div className="grid gap-8 md:grid-cols-3">
        {tiers.map((tier) => (
          <PricingCard
            key={tier.name}
            tier={{
              name: tier.name,
              price: billingPeriod === 'monthly' ? tier.monthlyPrice : tier.yearlyPrice,
              description: tier.description,
              features: tier.features,
              limitations: tier.limitations,
              cta: tier.cta,
              href: tier.href,
              popular: tier.popular,
            }}
            currencySymbol={currencySymbol}
            isAuthenticated={isAuthenticated}
            userTier={userTier}
            billingPeriod={billingPeriod}
          />
        ))}
      </div>
    </div>
  );
}
