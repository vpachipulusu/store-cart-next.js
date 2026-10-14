'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import {
  getSubscriptionDetailsAction,
  getPaymentMethodsAction,
  getSubscriptionInvoicesAction,
  createBillingPortalSessionAction,
} from '@/app/actions/subscription-actions';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Loader2, CreditCard, Calendar, Download, ExternalLink } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';

interface SubscriptionDetails {
  subscriptionTier: string;
  subscriptionStatus: string;
  currentPeriodEnd: string | null;
  hasStripeCustomer: boolean;
}

interface PaymentMethod {
  id: string;
  brand: string;
  last4: string;
  expMonth: number;
  expYear: number;
}

interface Invoice {
  id: string;
  amount: number;
  currency: string;
  status: string;
  created: string;
  pdfUrl: string | null;
  hostedUrl: string | null;
}

export default function BillingPage() {
  const { toast } = useToast();
  const [isLoading, setIsLoading] = useState(true);
  const [subscription, setSubscription] = useState<SubscriptionDetails | null>(null);
  const [paymentMethods, setPaymentMethods] = useState<PaymentMethod[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);

  const fetchData = useCallback(async () => {
    try {
      const [subResult, pmResult, invResult] = await Promise.all([
        getSubscriptionDetailsAction(),
        getPaymentMethodsAction(),
        getSubscriptionInvoicesAction(10),
      ]);

      return {
        subscription: subResult.success && subResult.data ? subResult.data : undefined,
        paymentMethods:
          pmResult.success && pmResult.data ? pmResult.data.paymentMethods : undefined,
        invoices: invResult.success && invResult.data ? invResult.data.invoices : undefined,
      };
    } catch (error) {
      console.error('Failed to load billing data:', error);
      toast({ title: 'Error', description: 'Failed to load billing data', variant: 'destructive' });
      return null;
    }
  }, [toast]);

  const applyBillingData = useCallback((data: Awaited<ReturnType<typeof fetchData>>) => {
    if (data?.subscription) setSubscription(data.subscription);
    if (data?.paymentMethods) setPaymentMethods(data.paymentMethods);
    if (data?.invoices) setInvoices(data.invoices);
    setIsLoading(false);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchData().then((data) => {
      if (!cancelled) applyBillingData(data);
    });
    return () => {
      cancelled = true;
    };
  }, [fetchData, applyBillingData]);

  /**
   * KAN-182: removing a card, choosing the default card and the auto-renewal toggle are switched off until the
   * backend exposes them; the Stripe customer portal covers all of them in the meantime.
   */
  const handleAddPaymentMethod = async () => {
    try {
      const result = await createBillingPortalSessionAction();
      if (result.success && result.data?.url) {
        window.location.href = result.data.url;
      } else {
        toast({
          title: 'Error',
          description: result.error || 'Failed to open billing portal',
          variant: 'destructive',
        });
      }
    } catch (error) {
      console.error('Open billing portal error:', error);
      toast({
        title: 'Error',
        description: 'An unexpected error occurred',
        variant: 'destructive',
      });
    }
  };

  if (isLoading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const isFreeTier = subscription?.subscriptionTier === 'free';
  const hasActiveSubscription = subscription?.subscriptionStatus === 'active' && !isFreeTier;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl tracking-tight">Billing & Subscription</h1>
        <p className="text-muted-foreground">Manage your subscription plan and payment methods</p>
      </div>

      {/* Current Plan */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CreditCard className="h-5 w-5 text-theme-accent" />
            Current Plan
          </CardTitle>
          <CardDescription>Your active subscription details</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between rounded-lg border p-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-lg font-semibold capitalize">
                  {subscription?.subscriptionTier} Plan
                </span>
                <Badge variant={hasActiveSubscription ? 'default' : 'secondary'}>
                  {hasActiveSubscription
                    ? 'Active'
                    : subscription?.subscriptionStatus || 'Inactive'}
                </Badge>
              </div>
              {subscription?.currentPeriodEnd && (
                <p className="text-sm text-muted-foreground">
                  Current period ends on{' '}
                  {new Date(subscription.currentPeriodEnd).toLocaleDateString()}
                </p>
              )}
            </div>
            <Button asChild variant={isFreeTier ? 'accent' : 'outline'}>
              <Link href="/pricing">{isFreeTier ? 'Upgrade Plan' : 'Change Plan'}</Link>
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* KAN-182: the auto-renewal badge, interval label and cancel/resume toggle are switched off until the billing
          API exposes cancel_at_period_end and the interval. */}

      {/* Payment Methods */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <CreditCard className="h-5 w-5 text-theme-accent" />
                Payment Methods
              </CardTitle>
              <CardDescription>Manage your saved payment methods</CardDescription>
            </div>
            {subscription?.hasStripeCustomer && (
              <Button variant="outline" onClick={handleAddPaymentMethod}>
                Add Payment Method
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {paymentMethods.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              No payment methods saved
            </p>
          ) : (
            <div className="space-y-3">
              {paymentMethods.map((pm) => (
                <div
                  key={pm.id}
                  className="flex items-center justify-between rounded-lg border p-4"
                >
                  <div className="flex items-center gap-3">
                    <CreditCard className="h-8 w-8 text-muted-foreground" />
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium capitalize">{pm.brand}</span>
                        <span className="text-muted-foreground">ending in {pm.last4}</span>
                      </div>
                      <p className="text-sm text-muted-foreground">
                        Expires {pm.expMonth.toString().padStart(2, '0')}/{pm.expYear}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
              <p className="text-sm text-muted-foreground">
                To remove a card or change your default card, use Add Payment Method to open the
                Stripe billing portal.
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Billing History */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Calendar className="h-5 w-5 text-theme-accent" />
            Billing History
          </CardTitle>
          <CardDescription>Your recent invoices and payments</CardDescription>
        </CardHeader>
        <CardContent>
          {invoices.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">No invoices yet</p>
          ) : (
            <div className="space-y-3">
              {invoices.map((invoice) => (
                <div
                  key={invoice.id}
                  className="flex items-center justify-between rounded-lg border p-4"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">
                        {(invoice.amount / 100).toLocaleString('en-US', {
                          style: 'currency',
                          currency: invoice.currency,
                        })}
                      </span>
                      <Badge variant={invoice.status === 'paid' ? 'default' : 'secondary'}>
                        {invoice.status}
                      </Badge>
                    </div>
                    <p className="text-sm text-muted-foreground">
                      {new Date(invoice.created).toLocaleDateString()}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {invoice.pdfUrl && (
                      <Button variant="ghost" asChild>
                        <a href={invoice.pdfUrl} target="_blank" rel="noopener noreferrer">
                          <Download className="h-4 w-4" />
                          <span className="ml-1">PDF</span>
                        </a>
                      </Button>
                    )}
                    {invoice.hostedUrl && (
                      <Button variant="ghost" asChild>
                        <a href={invoice.hostedUrl} target="_blank" rel="noopener noreferrer">
                          <ExternalLink className="h-4 w-4" />
                          <span className="ml-1">View</span>
                        </a>
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
