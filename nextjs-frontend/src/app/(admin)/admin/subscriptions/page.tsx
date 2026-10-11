import { db } from '@/lib/db/client';
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

async function getSubscriptionStats() {
  const prices = await getStripePrices();

  const totalSubscriptions = await db.user.count({
    where: {
      subscriptionStatus: 'active',
      subscriptionTier: {
        not: 'free',
      },
    },
  });

  const activeProSubscriptions = await db.user.count({
    where: {
      subscriptionTier: 'pro',
      subscriptionStatus: 'active',
    },
  });

  const activeEnterpriseSubscriptions = await db.user.count({
    where: {
      subscriptionTier: 'enterprise',
      subscriptionStatus: 'active',
    },
  });

  const canceledThisMonth = await db.user.count({
    where: {
      subscriptionStatus: 'canceled',
      updatedAt: {
        gte: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
      },
    },
  });

  const mrr =
    activeProSubscriptions * prices.pro.monthly +
    activeEnterpriseSubscriptions * prices.enterprise.monthly;

  const recentSubscriptions = await db.user.findMany({
    where: {
      subscriptionStatus: 'active',
      subscriptionTier: {
        not: 'free',
      },
    },
    select: {
      id: true,
      email: true,
      displayName: true,
      subscriptionTier: true,
      subscriptionStatus: true,
      stripeCurrentPeriodEnd: true,
      updatedAt: true,
    },
    orderBy: {
      updatedAt: 'desc',
    },
    take: 20,
  });

  return {
    totalSubscriptions,
    activeProSubscriptions,
    activeEnterpriseSubscriptions,
    canceledThisMonth,
    mrr,
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

      {/* Stats */}
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
              {stats.canceledThisMonth} canceled this month
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Recent Subscriptions */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Subscriptions</CardTitle>
          <CardDescription>
            Latest subscription activity and updates • Updated: {new Date().toLocaleTimeString()}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {stats.recentSubscriptions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Users className="mb-4 h-12 w-12 text-muted-foreground" />
              <h3 className="mb-2 text-lg font-semibold">No Active Subscriptions</h3>
              <p className="max-w-md text-sm text-muted-foreground">
                There are no active paid subscriptions yet. When users upgrade to Pro or Enterprise
                plans, they will appear here automatically.
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Customer</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Plan</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Renewal Date</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {stats.recentSubscriptions.map((user: any) => (
                  <TableRow key={user.id}>
                    <TableCell className="font-medium">
                      {user.displayName || user.email?.split('@')[0] || 'Unknown'}
                    </TableCell>
                    <TableCell>{user.email}</TableCell>
                    <TableCell>
                      <Badge className="capitalize">{user.subscriptionTier}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={user.subscriptionStatus === 'active' ? 'default' : 'secondary'}
                        className="capitalize"
                      >
                        {user.subscriptionStatus}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {user.stripeCurrentPeriodEnd
                        ? new Date(user.stripeCurrentPeriodEnd).toLocaleDateString()
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
    </div>
  );
}
