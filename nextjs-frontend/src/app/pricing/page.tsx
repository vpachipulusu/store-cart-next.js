import Link from 'next/link';
import { cookies } from 'next/headers';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { PricingCardsSection } from '@/components/pricing/pricing-cards-section';
import { adminAuth } from '@/lib/firebase/admin';
import { db } from '@/lib/db/client';
import { getSubscriptionPlans, getCurrencySymbol } from '@/config/subscriptions';

const TIER_UI_CONFIG: Record<string, {
  limitations: string[];
  cta: string;
  href: string;
}> = {
  free: {
    limitations: [
      'No priority support',
      'No advanced features',
      'No team collaboration',
      'Limited API access',
    ],
    cta: 'Get Started',
    href: '/signup',
  },
  pro: {
    limitations: [],
    cta: 'Start Free Trial',
    href: '/signup?plan=pro',
  },
  enterprise: {
    limitations: [],
    cta: 'Contact Sales',
    href: '/contact?plan=enterprise',
  },
};

async function getUserSession() {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get('session')?.value;

    if (!sessionCookie) {
      return { isAuthenticated: false };
    }

    const decodedClaims = await adminAuth.verifySessionCookie(sessionCookie, true);
    const user = await db.user.findUnique({
      where: { firebaseUid: decodedClaims.uid },
      select: {
        id: true,
        subscriptionTier: true,
      },
    });

    return {
      isAuthenticated: true,
      userTier: user?.subscriptionTier || 'free',
    };
  } catch (error) {
    return { isAuthenticated: false };
  }
}

export default async function PricingPage() {
  const session = await getUserSession();
  const [plans, currencySymbol] = await Promise.all([
    getSubscriptionPlans(),
    getCurrencySymbol(),
  ]);

  const tiers = plans.map((plan) => {
    const uiConfig = TIER_UI_CONFIG[plan.tier] ?? TIER_UI_CONFIG.free;
    return {
      name: plan.name,
      monthlyPrice: plan.price.monthly,
      yearlyPrice: plan.price.yearly,
      description: plan.description,
      features: plan.features,
      limitations: uiConfig.limitations,
      cta: uiConfig.cta,
      href: uiConfig.href,
      popular: plan.popular ?? false,
    };
  });

  return (
    <div className="min-h-screen px-4 py-12">
      <div className="mx-auto max-w-7xl">
        {/* Header */}
        <div className="mb-12 text-center">
          <h1 className="mb-4 text-4xl tracking-tight">Simple, Transparent Pricing</h1>
          <p className="mx-auto max-w-2xl text-xl text-muted-foreground">
            Choose the plan that&apos;s right for you. All plans include a 14-day free trial.
          </p>
        </div>

        <div className="divider-accent mx-auto max-w-[600px]" />

        {/* Billing Toggle + Pricing Cards */}
        <PricingCardsSection
          tiers={tiers}
          currencySymbol={currencySymbol}
          isAuthenticated={session.isAuthenticated}
          userTier={session.userTier}
        />

        {/* FAQ Section */}
        <div className="mx-auto max-w-3xl">
          <h2 className="mb-8 text-center text-3xl font-bold">Frequently Asked Questions</h2>

          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Can I change my plan later?</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-muted-foreground">
                  Yes! You can upgrade or downgrade your plan at any time. Changes will be prorated
                  based on your current billing cycle.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-lg">What payment methods do you accept?</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-muted-foreground">
                  We accept all major credit cards (Visa, MasterCard, American Express, Discover)
                  through our secure payment processor, Stripe.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Do you offer refunds?</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-muted-foreground">
                  Yes, we offer a 30-day money-back guarantee. If you&apos;re not satisfied with our
                  service, contact us for a full refund.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-lg">What&apos;s the difference between monthly and yearly?</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-muted-foreground">
                  Monthly plans are billed every month and can be canceled anytime. Yearly plans are
                  billed as a single annual payment at a discounted rate. Both plans auto-renew, and
                  you can turn off auto-renewal from your billing settings at any time.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Is there a free trial?</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-muted-foreground">
                  Yes! All paid plans come with a 14-day free trial. No credit card required to
                  start.
                </p>
              </CardContent>
            </Card>
          </div>
        </div>

        {/* CTA Section */}
        <div className="mt-16 text-center">
          <Card className="bg-gradient-to-br from-theme-surface to-theme-surface-light text-white dark:border dark:border-theme-accent/20 dark:from-theme-accent/[0.08] dark:to-theme-accent/[0.02]">
            <CardContent className="py-12">
              <h2 className="mb-4 text-3xl font-bold">Ready to get started?</h2>
              <p className="mb-6 text-lg opacity-90">
                Join thousands of satisfied customers today.
              </p>
              <div className="flex justify-center gap-4">
                <Button asChild size="lg" className="bg-theme-accent text-white hover:bg-theme-accent-dark">
                  <Link href="/signup">Start Free Trial</Link>
                </Button>
                <Button asChild size="lg" variant="outline" className="bg-transparent border-white/30 text-white hover:bg-white/10">
                  <Link href="/contact">Contact Sales</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
