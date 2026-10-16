'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import {
  getSubscriptionDetailsAction,
  getPaymentMethodsAction,
  getSubscriptionInvoicesAction,
  createBillingPortalSessionAction,
  cancelSubscriptionAction,
  resumeSubscriptionAction,
  deletePaymentMethodAction,
  setDefaultPaymentMethodAction,
} from '@/app/actions/subscription-actions';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Switch } from '@/components/ui/switch';
import { SubscriptionStatusPill } from '@/components/dashboard/billing/billing-pills';
import { InvoiceTable, type Invoice } from '@/components/dashboard/billing/invoice-table';
import { planUsageFixture } from '@/components/dashboard/billing/plan-usage-fixtures';
import { PlanUsageMeter } from '@/components/dashboard/plan-usage-meter';
import { Loader2, CreditCard, Calendar, Gauge, RefreshCw } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';

interface SubscriptionDetails {
  subscriptionTier: string;
  subscriptionStatus: string;
  currentPeriodEnd: string | null;
  hasStripeCustomer: boolean;
  /** `null` when the price is not in the backend catalogue. */
  billingPeriod: 'monthly' | 'yearly' | null;
  autoRenewal: boolean;
}

interface PaymentMethod {
  id: string;
  brand: string;
  last4: string;
  expMonth: number;
  expYear: number;
  isDefault: boolean;
}

type ActionResult = { success: boolean; data?: { message?: string }; error?: string };

export default function BillingPage() {
  const { toast } = useToast();
  const [isLoading, setIsLoading] = useState(true);
  const [subscription, setSubscription] = useState<SubscriptionDetails | null>(null);
  const [paymentMethods, setPaymentMethods] = useState<PaymentMethod[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

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
    if (!data) setErrorMessage('Failed to load billing data');
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

  /** Runs one billing action: toast the backend's curated message, then refresh the page data. */
  const runAction = async (key: string, action: () => Promise<ActionResult>, fallback: string) => {
    setBusyAction(key);
    setErrorMessage(null);
    try {
      const result = await action();
      if (result.success) {
        toast({ title: 'Success', description: result.data?.message });
        applyBillingData(await fetchData());
      } else {
        setErrorMessage(result.error || fallback);
      }
    } catch (error) {
      console.error(`Billing action ${key} failed:`, error);
      setErrorMessage('An unexpected error occurred');
    } finally {
      setBusyAction(null);
    }
  };

  const handleToggleAutoRenewal = (renew: boolean) =>
    runAction(
      'auto-renewal',
      renew ? resumeSubscriptionAction : cancelSubscriptionAction,
      'Failed to update auto-renewal'
    );

  const handleSetDefault = (id: string) =>
    runAction(
      `default:${id}`,
      () => setDefaultPaymentMethodAction(id),
      'Failed to update default payment method'
    );

  const handleDeleteCard = (id: string) =>
    runAction(
      `delete:${id}`,
      () => deletePaymentMethodAction(id),
      'Failed to remove payment method'
    );

  const handleAddPaymentMethod = async () => {
    setErrorMessage(null);
    try {
      const result = await createBillingPortalSessionAction();
      if (result.success && result.data?.url) {
        window.location.href = result.data.url;
      } else {
        setErrorMessage(result.error || 'Failed to open billing portal');
      }
    } catch (error) {
      console.error('Open billing portal error:', error);
      setErrorMessage('An unexpected error occurred');
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
  const autoRenewal = hasActiveSubscription && Boolean(subscription?.autoRenewal);
  const intervalLabel =
    hasActiveSubscription && subscription?.billingPeriod
      ? `Billed ${subscription.billingPeriod}`
      : null;
  const periodEndText = !hasActiveSubscription
    ? 'Current period ends on'
    : autoRenewal
      ? 'Renews on'
      : 'Expires on';

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl tracking-tight">Billing & Subscription</h1>
        <p className="text-muted-foreground">Manage your subscription plan and payment methods</p>
      </div>

      {errorMessage && (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage}</AlertDescription>
        </Alert>
      )}

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
          <div
            role="group"
            aria-label="Current plan"
            className="flex items-center justify-between rounded-lg border p-4"
          >
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-lg font-semibold capitalize">
                  {subscription?.subscriptionTier} Plan
                </span>
                <SubscriptionStatusPill
                  status={subscription?.subscriptionStatus}
                  isActive={hasActiveSubscription}
                />
                {intervalLabel && <Badge variant="outline">{intervalLabel}</Badge>}
              </div>
              {subscription?.currentPeriodEnd && (
                <p className="text-sm text-muted-foreground">
                  {periodEndText} {new Date(subscription.currentPeriodEnd).toLocaleDateString()}
                </p>
              )}
            </div>
            <Button asChild variant={isFreeTier ? 'accent' : 'outline'}>
              <Link href="/pricing">{isFreeTier ? 'Upgrade Plan' : 'Change Plan'}</Link>
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Auto-Renewal: active subscribers only. Only owners and admins resolve a billing organisation. */}
      {hasActiveSubscription && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <RefreshCw className="h-5 w-5 text-theme-accent" />
              Auto-Renewal
            </CardTitle>
            <CardDescription>
              Control whether your subscription renews automatically
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between rounded-lg border p-4">
              <div className="space-y-1">
                <p className="font-medium">
                  {autoRenewal ? 'Auto-renewal is on' : 'Auto-renewal is off'}
                </p>
                <p className="text-sm text-muted-foreground">
                  {autoRenewal
                    ? 'Your subscription will renew automatically at the end of the period.'
                    : 'Your subscription will expire at the end of the current period.'}
                </p>
              </div>
              <Switch
                aria-label="Auto-renewal"
                checked={autoRenewal}
                disabled={busyAction !== null}
                onCheckedChange={handleToggleAutoRenewal}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Plan usage: no usage API exists, so the meters come from typed sample fixtures. */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Gauge className="h-5 w-5 text-theme-accent" />
            Plan Usage
          </CardTitle>
          <CardDescription>Sample figures: live plan usage is not available yet.</CardDescription>
        </CardHeader>
        <CardContent>
          <PlanUsageMeter
            items={planUsageFixture(subscription?.subscriptionTier)}
            className="rounded-none border-0 bg-transparent p-0"
            compareAction={{ label: 'Compare plans', href: '/pricing' }}
          />
        </CardContent>
      </Card>

      {/* Upcoming invoice: the API has no route for it, so the panel stays switched off. */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Calendar className="h-5 w-5 text-theme-accent" />
            Upcoming Invoice
          </CardTitle>
          <CardDescription>Preview of your next charge</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="py-4 text-center text-sm text-muted-foreground">
            The upcoming invoice preview is not available yet.
          </p>
        </CardContent>
      </Card>

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
                        {pm.isDefault && <Badge variant="secondary">Default</Badge>}
                      </div>
                      <p className="text-sm text-muted-foreground">
                        Expires {pm.expMonth.toString().padStart(2, '0')}/{pm.expYear}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {!pm.isDefault && (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busyAction !== null}
                        onClick={() => handleSetDefault(pm.id)}
                      >
                        Set as default
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busyAction !== null}
                      onClick={() => handleDeleteCard(pm.id)}
                    >
                      Remove
                    </Button>
                  </div>
                </div>
              ))}
              {hasActiveSubscription && (
                <p className="text-sm text-muted-foreground">
                  The default card cannot be removed while you have a subscription. Set another card
                  as default first.
                </p>
              )}
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
            <InvoiceTable invoices={invoices} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
