import { adminErrorMessage } from '@/lib/api/admin-errors';
import { fetchAdminRevenue } from '@/lib/api/admin-analytics';
import { fetchAdminSubscriptions } from '@/lib/api/admin-subscriptions';
import type { ApiResult } from '@/lib/api/server';
import { logger } from '@/lib/logger';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { KpiStrip, type KpiCell } from '@/components/dashboard/kpi-strip';
import { RefreshButton } from '@/components/admin/refresh-button';
import { InlineError } from '../_components/inline-error';
import { formatMinorUnits } from '../_components/format-money';
import { SubscriptionsTable } from './subscriptions-table';
import { SyncPanel } from './sync-panel';

// Force dynamic rendering to always show latest subscription data
export const dynamic = 'force-dynamic';
export const revalidate = 0;

const RECENT_LIMIT = 20;
const SUBSCRIPTIONS_HREF = '/admin/subscriptions';

function failure(result: Extract<ApiResult<unknown>, { success: false }>) {
  logger.error('Admin subscriptions page: list failed', { status: result.status });
  return { error: adminErrorMessage(result) } as const;
}

/** Revenue only feeds the MRR figure, so a failure must not hide the counts and the table. */
async function loadRevenue() {
  const result = await fetchAdminRevenue();
  if (result.success) return result.data;
  logger.error('Admin subscriptions page: revenue failed', { status: result.status });
  return null;
}

async function getSubscriptionStats() {
  const [revenue, pro, enterprise, canceled] = await Promise.all([
    loadRevenue(),
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
    mrr: revenue ? formatMinorUnits(revenue.mrr_minor, revenue.currency) : null,
    revenueComplete: revenue?.complete ?? true,
    recentSubscriptions,
  };
}

type Stats = Extract<Awaited<ReturnType<typeof getSubscriptionStats>>, { error: null }>;

function kpiCells(stats: Stats): KpiCell[] {
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
      ? { id: 'mrr', label: 'MRR', state: 'empty', emptyText: 'Revenue unavailable' }
      : {
          id: 'mrr',
          label: 'MRR',
          state: 'ready',
          value: stats.mrr,
        },
  ];
}

export default async function AdminSubscriptionsPage() {
  const stats = await getSubscriptionStats();

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
            <KpiStrip cells={kpiCells(stats)} />
            <p className="text-sm text-muted-foreground">
              {stats.canceledSubscriptions} canceled (all time)
              {stats.revenueComplete
                ? ''
                : '. Some paying organisations could not be priced, so MRR is a minimum'}
            </p>
          </div>

          <SyncPanel />

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
                  <p className="mb-2 text-lg font-semibold">No Active Subscriptions</p>
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
