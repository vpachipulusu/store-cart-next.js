import { adminErrorMessage } from '@/lib/api/admin-users';
import { fetchAdminSubscriptions } from '@/lib/api/admin-subscriptions';
import type { ApiResult } from '@/lib/api/server';
import { logger } from '@/lib/logger';
import { getStripePrices, getCurrencySymbol } from '@/config/subscriptions';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DollarSign, TrendingUp, TrendingDown, Users, CreditCard } from 'lucide-react';
import { RefreshButton } from '@/components/admin/refresh-button';

// Force dynamic rendering to always show latest subscription data
export const dynamic = 'force-dynamic';
export const revalidate = 0;

const RECENT_LIMIT = 20;

function failure(result: Extract<ApiResult<unknown>, { success: false }>) {
  logger.error('Admin subscriptions page: list failed', { status: result.status });
  return { error: adminErrorMessage(result) } as const;
}

async function getSubscriptionStats() {
  const [prices, pro, enterprise, canceled] = await Promise.all([
    getStripePrices(),
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
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, RECENT_LIMIT);

  return {
    error: null,
    totalSubscriptions: activeProSubscriptions + activeEnterpriseSubscriptions,
    activeProSubscriptions,
    activeEnterpriseSubscriptions,
    canceledSubscriptions: canceled.data.total_count,
    mrr:
      activeProSubscriptions * prices.pro.monthly +
      activeEnterpriseSubscriptions * prices.enterprise.monthly,
    proMonthlyPrice: prices.pro.monthly,
    enterpriseMonthlyPrice: prices.enterprise.monthly,
    recentSubscriptions,
  };
}

export default async function AdminSubscriptionsPage() {
  const [stats, currencySymbol] = await Promise.all([getSubscriptionStats(), getCurrencySymbol()]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Subscription Management</h1>
          <p className="text-muted-foreground">Monitor and manage all subscriptions</p>
        </div>
        <RefreshButton />
      </div>

      {stats.error !== null ? (
        <p role="alert" className="py-8 text-center text-sm text-destructive">
          {stats.error}
        </p>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Total Active</CardTitle>
                <Users className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stats.totalSubscriptions}</div>
                <p className="text-xs text-muted-foreground">Active subscriptions</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Pro Plans</CardTitle>
                <CreditCard className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stats.activeProSubscriptions}</div>
                <p className="text-xs text-muted-foreground">
                  {currencySymbol}
                  {stats.proMonthlyPrice}/month each
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Enterprise Plans</CardTitle>
                <TrendingUp className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stats.activeEnterpriseSubscriptions}</div>
                <p className="text-xs text-muted-foreground">
                  {currencySymbol}
                  {stats.enterpriseMonthlyPrice}/month each
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">MRR</CardTitle>
                <DollarSign className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {currencySymbol}
                  {stats.mrr.toLocaleString()}
                </div>
                <p className="text-xs text-muted-foreground">
                  {stats.canceledSubscriptions} canceled (all time)
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Recent Subscriptions */}
          <Card>
            <CardHeader>
              <CardTitle>Recent Subscriptions</CardTitle>
              <CardDescription>
                Latest subscription activity and updates • Updated:{' '}
                {new Date().toLocaleTimeString()}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {stats.recentSubscriptions.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <Users className="mb-4 h-12 w-12 text-muted-foreground" />
                  <h3 className="mb-2 text-lg font-semibold">No Active Subscriptions</h3>
                  <p className="max-w-md text-sm text-muted-foreground">
                    There are no active paid subscriptions yet. When users upgrade to Pro or
                    Enterprise plans, they will appear here automatically.
                  </p>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Organisation</TableHead>
                      <TableHead>Slug</TableHead>
                      <TableHead>Plan</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Renewal Date</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {stats.recentSubscriptions.map((subscription) => (
                      <TableRow key={subscription.organization_id}>
                        <TableCell className="font-medium">{subscription.name}</TableCell>
                        <TableCell>{subscription.slug}</TableCell>
                        <TableCell>
                          <Badge className="capitalize">{subscription.plan}</Badge>
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={subscription.status === 'active' ? 'default' : 'secondary'}
                            className="capitalize"
                          >
                            {subscription.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {subscription.current_period_end
                            ? new Date(subscription.current_period_end).toLocaleDateString()
                            : '—'}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button variant="ghost" size="sm">
                            Manage
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
