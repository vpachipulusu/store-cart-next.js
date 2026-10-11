'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  getSubscriptionDetailsAction,
  getPaymentMethodsAction,
  getSubscriptionInvoicesAction,
  cancelSubscriptionAction,
  resumeSubscriptionAction,
  deletePaymentMethodAction,
  setDefaultPaymentMethodAction,
  createBillingPortalSessionAction,
} from '@/app/actions/subscription-actions';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Separator } from '@/components/ui/separator';
import {
  Loader2,
  CreditCard,
  Calendar,
  RefreshCw,
  Trash2,
  Star,
  Download,
  ExternalLink,
} from 'lucide-react';
import { useToast } from '@/hooks/use-toast';

interface SubscriptionDetails {
  subscriptionTier: string;
  subscriptionStatus: string;
  billingPeriod: 'monthly' | 'yearly' | null;
  autoRenewal: boolean;
  currentPeriodEnd: string | null;
  hasStripeCustomer: boolean;
}

interface PaymentMethod {
  id: string;
  brand: string;
  last4: string;
  expMonth: number;
  expYear: number;
  isDefault: boolean;
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
  const router = useRouter();
  const { toast } = useToast();
  const [isLoading, setIsLoading] = useState(true);
  const [subscription, setSubscription] = useState<SubscriptionDetails | null>(null);
  const [paymentMethods, setPaymentMethods] = useState<PaymentMethod[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [isTogglingRenewal, setIsTogglingRenewal] = useState(false);
  const [deletingPaymentId, setDeletingPaymentId] = useState<string | null>(null);
  const [settingDefaultId, setSettingDefaultId] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      setIsLoading(true);
      const [subResult, pmResult, invResult] = await Promise.all([
        getSubscriptionDetailsAction(),
        getPaymentMethodsAction(),
        getSubscriptionInvoicesAction(10),
      ]);

      if (subResult.success && subResult.data) {
        setSubscription(subResult.data);
      }
      if (pmResult.success && pmResult.data) {
        setPaymentMethods(pmResult.data.paymentMethods);
      }
      if (invResult.success && invResult.data) {
        setInvoices(invResult.data.invoices);
      }
    } catch (error) {
      console.error('Failed to load billing data:', error);
      toast({ title: 'Error', description: 'Failed to load billing data', variant: 'destructive' });
    } finally {
      setIsLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleToggleAutoRenewal = async () => {
    if (!subscription) return;

    // Don't allow enabling auto-renewal if there's no active subscription
    if (
      !subscription.autoRenewal &&
      (!hasActiveSubscription || subscription.subscriptionStatus !== 'active')
    ) {
      toast({
        title: 'Cannot Enable Auto-Renewal',
        description:
          'You need an active subscription to enable auto-renewal. Please upgrade your plan first.',
        variant: 'destructive',
      });
      return;
    }

    setIsTogglingRenewal(true);
    try {
      const result = subscription.autoRenewal
        ? await cancelSubscriptionAction()
        : await resumeSubscriptionAction();

      if (result.success) {
        toast({
          title: 'Success',
          description: subscription.autoRenewal
            ? 'Auto-renewal turned off. Your plan will expire at the end of the billing period.'
            : 'Auto-renewal turned on. Your subscription will renew automatically.',
        });
        await loadData();
        router.refresh();
      } else {
        toast({
          title: 'Error',
          description: result.error || 'Failed to update auto-renewal',
          variant: 'destructive',
        });
      }
    } catch (error) {
      console.error('Toggle auto-renewal error:', error);
      toast({
        title: 'Error',
        description: 'An unexpected error occurred',
        variant: 'destructive',
      });
    } finally {
      setIsTogglingRenewal(false);
    }
  };

  const handleDeletePaymentMethod = async (paymentMethodId: string) => {
    setDeletingPaymentId(paymentMethodId);
    try {
      const result = await deletePaymentMethodAction(paymentMethodId);
      if (result.success) {
        toast({ title: 'Success', description: 'Payment method removed' });
        await loadData();
      } else {
        toast({
          title: 'Error',
          description: result.error || 'Failed to remove payment method',
          variant: 'destructive',
        });
      }
    } catch (error) {
      console.error('Delete payment method error:', error);
      toast({
        title: 'Error',
        description: 'An unexpected error occurred',
        variant: 'destructive',
      });
    } finally {
      setDeletingPaymentId(null);
    }
  };

  const handleSetDefaultPaymentMethod = async (paymentMethodId: string) => {
    setSettingDefaultId(paymentMethodId);
    try {
      const result = await setDefaultPaymentMethodAction(paymentMethodId);
      if (result.success) {
        toast({ title: 'Success', description: 'Default payment method updated' });
        await loadData();
      } else {
        toast({
          title: 'Error',
          description: result.error || 'Failed to update default payment method',
          variant: 'destructive',
        });
      }
    } catch (error) {
      console.error('Set default payment method error:', error);
      toast({
        title: 'Error',
        description: 'An unexpected error occurred',
        variant: 'destructive',
      });
    } finally {
      setSettingDefaultId(null);
    }
  };

  const handleAddPaymentMethod = async () => {
    try {
      const result = await createBillingPortalSessionAction(
        `${window.location.origin}/dashboard/settings/billing`
      );
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
  const isCanceling =
    subscription?.subscriptionStatus === 'canceling' ||
    (!subscription?.autoRenewal && hasActiveSubscription);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl tracking-tight">Billing & Subscription</h1>
        <p className="text-muted-foreground">
          Manage your subscription plan, auto-renewal, and payment methods
        </p>
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
                {isCanceling && <Badge variant="destructive">Cancels at period end</Badge>}
              </div>
              {subscription?.billingPeriod && (
                <p className="text-sm text-muted-foreground">
                  Billed {subscription.billingPeriod === 'yearly' ? 'annually' : 'monthly'}
                </p>
              )}
              {subscription?.currentPeriodEnd && (
                <p className="text-sm text-muted-foreground">
                  {isCanceling ? 'Expires' : 'Renews'} on{' '}
                  {new Date(subscription.currentPeriodEnd).toLocaleDateString()}
                </p>
              )}
              {!subscription?.currentPeriodEnd && isCanceling && (
                <p className="text-sm text-muted-foreground">
                  Will expire at the end of the current billing period
                </p>
              )}
            </div>
            <Button asChild variant={isFreeTier ? 'default' : 'outline'} className={isFreeTier ? 'bg-theme-accent text-white hover:bg-theme-accent-dark' : ''}>
              <Link href="/pricing">{isFreeTier ? 'Upgrade Plan' : 'Change Plan'}</Link>
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Auto-Renewal Toggle */}
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
            <div className="flex flex-row items-center justify-between rounded-lg border p-4">
              <div className="space-y-1">
                <p className="text-base font-medium">Auto-Renewal</p>
                <p className="text-sm text-muted-foreground">
                  {subscription?.autoRenewal
                    ? `Your subscription will renew automatically${subscription?.currentPeriodEnd ? ` on ${new Date(subscription.currentPeriodEnd).toLocaleDateString()}` : ' at the end of each billing period'}.`
                    : `Your subscription will expire${subscription?.currentPeriodEnd ? ` on ${new Date(subscription.currentPeriodEnd).toLocaleDateString()}` : ' at the end of the billing period'}. Turn on to continue your plan.`}
                </p>
              </div>
              <Switch
                checked={subscription?.autoRenewal ?? false}
                onCheckedChange={handleToggleAutoRenewal}
                disabled={isTogglingRenewal}
              />
            </div>
          </CardContent>
        </Card>
      )}

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
              <Button variant="outline" size="sm" onClick={handleAddPaymentMethod}>
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
                        variant="ghost"
                        size="sm"
                        onClick={() => handleSetDefaultPaymentMethod(pm.id)}
                        disabled={settingDefaultId === pm.id}
                      >
                        {settingDefaultId === pm.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Star className="h-4 w-4" />
                        )}
                        <span className="ml-1">Set Default</span>
                      </Button>
                    )}
                    {/* Show remove button unless it's default payment method on a paid plan */}
                    {(!pm.isDefault || isFreeTier) && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDeletePaymentMethod(pm.id)}
                        disabled={deletingPaymentId === pm.id}
                        title="Remove payment method"
                      >
                        {deletingPaymentId === pm.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Trash2 className="h-4 w-4" />
                        )}
                        <span className="ml-1">Remove</span>
                      </Button>
                    )}
                  </div>
                </div>
              ))}
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
                      <Button variant="ghost" size="sm" asChild>
                        <a href={invoice.pdfUrl} target="_blank" rel="noopener noreferrer">
                          <Download className="h-4 w-4" />
                          <span className="ml-1">PDF</span>
                        </a>
                      </Button>
                    )}
                    {invoice.hostedUrl && (
                      <Button variant="ghost" size="sm" asChild>
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
