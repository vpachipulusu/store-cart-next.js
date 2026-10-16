import { adminErrorMessage } from '@/lib/api/admin-errors';
import { fetchAdminSubscriptions } from '@/lib/api/admin-subscriptions';
import type { ApiResult } from '@/lib/api/server';
import { logger } from '@/lib/logger';
import { getStripePrices, getCurrencySymbol } from '@/config/subscriptions';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { KpiStrip, type KpiCell } from '@/components/dashboard/kpi-strip';
import { RefreshButton } from '@/components/admin/refresh-button';
import { InlineError } from '../_components/inline-error';
import { SubscriptionsTable } from './subscriptions-table';

// Force dynamic rendering to always show latest subscription data
export const dynamic = 'force-dynamic';
export const revalidate = 0;

const RECENT_LIMIT = 20;
const SUBSCRIPTIONS_HREF = '/admin/subscriptions';

function failure(result: Extract<ApiResult<unknown>, { success: false }>) {
  logger.error('Admin subscriptions page: list failed', { status: result.status });
  return { error: adminErrorMessage(result) } as const;
}

/** Prices only feed the MRR figure, so a failure must not hide the counts and the table. */
async function loadPrices() {
  try {
    return await getStripePrices();
  } catch (error) {
    logger.error('Admin subscriptions page: Stripe prices failed', { error });
    return null;
  }
}

async function getSubscriptionStats() {
  const [prices, pro, enterprise, canceled] = await Promise.all([
    loadPrices(),
    fetchAdminSubscriptions({ status: 'active', plan: 'pro', limit: RECENT_LIMIT }),
    fetchAdminSubscriptions({ status: 'active', plan: 'enterprise', limit: RECENT_LIMIT }),
    fetchAdminSubscriptions({ status: 'canceled', limit: 1 }),
  ]);

  if (!pro.success) return failure(pro);
  if (!enterprise.success) return failure(enterprise);
  if (!canceled.success) return failure(canceled);

  const activeProSubscriptions = pro.data.total_count;
  const activeEnterpriseSubscriptions = enterprise.data.total_count;
  const recentSubscriptions = [...pro.data.subscriptions, ...enterprise.data.subscriptions]
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
    .slice(0, RECENT_LIMIT);

  return {
    error: null,
    totalSubscriptions: activeProSubscriptions + activeEnterpriseSubscriptions,
    activeProSubscriptions,
    activeEnterpriseSubscriptions,
    canceledSubscriptions: canceled.data.total_count,
    mrr: prices
      ? activeProSubscriptions * prices.pro.monthly +
        activeEnterpriseSubscriptions * prices.enterprise.monthly
      : null,
    proMonthlyPrice: prices?.pro.monthly ?? null,
    enterpriseMonthlyPrice: prices?.enterprise.monthly ?? null,
    recentSubscriptions,
  };
}

function priceText(price: number | null, currencySymbol: string): string {
  return price === null ? 'Price unavailable' : `${currencySymbol}${price}/month each`;
}

type Stats = Extract<Awaited<ReturnType<typeof getSubscriptionStats>>, { error: null }>;

function kpiCells(stats: Stats, currencySymbol: string): KpiCell[] {
  return [
    { id: 'total', label: 'Total active', state: 'ready', value: String(stats.totalSubscriptions) },
    { id: 'pro', label: 'Pro plans', state: 'ready', value: String(stats.activeProSubscriptions) },
    {
      id: 'enterprise',
      label: 'Enterprise plans',
      state: 'ready',
      value: String(stats.activeEnterpriseSubscriptions),
    },
    stats.mrr === null
      ? { id: 'mrr', label: 'MRR', state: 'empty', emptyText: 'Price unavailable' }
      : {
          id: 'mrr',
          label: 'MRR',
          state: 'ready',
          value: `${currencySymbol}${stats.mrr.toLocaleString()}`,
        },
  ];
}

export default async function AdminSubscriptionsPage() {
  const [stats, currencySymbol] = await Promise.all([getSubscriptionStats(), getCurrencySymbol()]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Subscription Management</h1>
          <p className="text-muted-foreground">Monitor and manage all subscriptions</p>
        </div>
        <RefreshButton />
      </div>

      {stats.error !== null ? (
        <InlineError message={stats.error} retryHref={SUBSCRIPTIONS_HREF} />
      ) : (
        <>
          <div className="space-y-2">
            <KpiStrip cells={kpiCells(stats, currencySymbol)} />
            <p className="text-sm text-muted-foreground">
              Pro: {priceText(stats.proMonthlyPrice, currencySymbol)}. Enterprise:{' '}
              {priceText(stats.enterpriseMonthlyPrice, currencySymbol)}.{' '}
              {stats.canceledSubscriptions} canceled (all time)
            </p>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Newest paid organisations</CardTitle>
              <CardDescription>
                Newest first by creation date, up to {RECENT_LIMIT} of the paid organisations
              </CardDescription>
            </CardHeader>
            <CardContent>
              {stats.recentSubscriptions.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <h3 className="mb-2 text-lg font-semibold">No Active Subscriptions</h3>
                  <p className="max-w-md text-sm text-muted-foreground">
                    There are no active paid subscriptions yet. When users upgrade to Pro or
                    Enterprise plans, they will appear here automatically.
                  </p>
                </div>
              ) : (
                <SubscriptionsTable subscriptions={stats.recentSubscriptions} />
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
