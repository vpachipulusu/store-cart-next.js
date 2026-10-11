'use client';

import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Check, X } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { createCheckoutSessionAction } from '@/app/actions/subscription-actions';
import { useState } from 'react';

interface PricingCardProps {
  tier: {
    name: string;
    price: number;
    description: string;
    features: string[];
    limitations: string[];
    cta: string;
    href: string;
    popular: boolean;
  };
  currencySymbol: string;
  isAuthenticated: boolean;
  userTier?: string;
  billingPeriod?: 'monthly' | 'yearly';
}

export function PricingCard({
  tier,
  currencySymbol,
  isAuthenticated,
  userTier,
  billingPeriod = 'monthly',
}: PricingCardProps) {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);

  const handleCTAClick = async (e: React.MouseEvent) => {
    // Enterprise - always go to contact
    if (tier.name === 'Enterprise') {
      return; // Let the Link handle it
    }

    // Free tier - go to signup or dashboard
    if (tier.name === 'Free') {
      return; // Let the Link handle it
    }

    // Pro tier with authenticated user
    if (isAuthenticated && tier.name === 'Pro') {
      e.preventDefault();
      setIsLoading(true);

      try {
        // Create checkout session - price ID is resolved server-side
        const result = await createCheckoutSessionAction(
          'pro',
          billingPeriod,
          `${window.location.origin}/dashboard?upgrade=success`,
          `${window.location.origin}/pricing?upgrade=cancelled`
        );

        if (result.success && result.data?.url) {
          // Redirect to Stripe Checkout
          window.location.href = result.data.url;
        } else {
          throw new Error(result.error || 'Failed to create checkout session');
        }
      } catch (error) {
        console.error('Checkout error:', error);
        alert('Failed to start checkout. Please try again or contact support.');
        setIsLoading(false);
      }
    }
  };

  // Determine CTA text and state
  const getCTAConfig = () => {
    if (tier.name === 'Free') {
      if (isAuthenticated) {
        if (userTier === 'free') {
          return { text: 'Current Plan', disabled: true, href: '#' };
        }
        return { text: 'Downgrade', disabled: false, href: '/dashboard/settings/billing' };
      }
      return { text: tier.cta, disabled: false, href: tier.href };
    }

    if (tier.name === 'Pro') {
      if (isAuthenticated) {
        if (userTier === 'pro') {
          return { text: 'Current Plan', disabled: true, href: '#' };
        }
        if (userTier === 'enterprise') {
          return { text: 'Downgrade', disabled: true, href: '/settings' };
        }
        return { text: 'Upgrade to Pro', disabled: false, href: '#' };
      }
      return { text: tier.cta, disabled: false, href: tier.href };
    }

    if (tier.name === 'Enterprise') {
      if (isAuthenticated && userTier === 'enterprise') {
        return { text: 'Current Plan', disabled: true, href: '#' };
      }
      return { text: tier.cta, disabled: false, href: tier.href };
    }

    return { text: tier.cta, disabled: false, href: tier.href };
  };

  const ctaConfig = getCTAConfig();

  // For yearly billing, show monthly equivalent as main price
  const displayPrice =
    billingPeriod === 'yearly' && tier.price > 0
      ? Math.round((tier.price / 12) * 100) / 100
      : tier.price;

  const priceLabel = tier.price > 0 ? '/month' : '';

  return (
    <Card className={`theme-card ${tier.popular ? 'relative overflow-hidden scale-105 border-theme-accent/40 shadow-xl shadow-theme-accent/10' : ''}`}>
      {tier.popular && <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-theme-accent-dark via-theme-accent to-theme-accent-dark" />}
      <CardHeader>
        <div className="mb-4 flex items-center justify-between">
          <CardTitle className="text-2xl">{tier.name}</CardTitle>
          {tier.popular && <Badge className="bg-theme-accent text-white border-0">Most Popular</Badge>}
          {isAuthenticated && userTier === tier.name.toLowerCase() && (
            <Badge variant="secondary">Active</Badge>
          )}
        </div>
        <div className="mb-4">
          <span className="text-4xl font-bold">
            {currencySymbol}
            {displayPrice}
          </span>
          {tier.price > 0 && <span className="text-muted-foreground">{priceLabel}</span>}
          {billingPeriod === 'yearly' && tier.price > 0 && (
            <p className="mt-1 text-sm text-muted-foreground">
              {currencySymbol}
              {tier.price} billed annually
            </p>
          )}
          {billingPeriod === 'monthly' && tier.price > 0 && (
            <p className="mt-1 text-sm text-muted-foreground">Cancel anytime</p>
          )}
        </div>
        <CardDescription>{tier.description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Features */}
        <div className="space-y-3">
          {tier.features.map((feature) => (
            <div key={feature} className="flex items-start gap-2">
              <Check className="mt-0.5 h-5 w-5 shrink-0 text-theme-accent" />
              <span className="text-sm">{feature}</span>
            </div>
          ))}

          {tier.limitations.map((limitation) => (
            <div key={limitation} className="flex items-start gap-2 text-muted-foreground">
              <X className="mt-0.5 h-5 w-5 shrink-0" />
              <span className="text-sm">{limitation}</span>
            </div>
          ))}
        </div>

        {/* CTA */}
        <Button
          asChild={tier.name !== 'Pro' || !isAuthenticated}
          className={`w-full ${tier.popular ? 'bg-theme-accent text-white hover:bg-theme-accent-dark' : ''}`}
          variant={tier.popular ? 'default' : 'outline'}
          size="lg"
          disabled={ctaConfig.disabled || isLoading}
          onClick={tier.name === 'Pro' && isAuthenticated ? handleCTAClick : undefined}
        >
          {tier.name !== 'Pro' || !isAuthenticated ? (
            <Link href={ctaConfig.href}>{isLoading ? 'Processing...' : ctaConfig.text}</Link>
          ) : (
            <span>{isLoading ? 'Processing...' : ctaConfig.text}</span>
          )}
        </Button>
      </CardContent>
    </Card>
  );
}
