import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { db } from '@/lib/db/client';
import { getStripePrices, getCurrencySymbol } from '@/config/subscriptions';
import { Users, TrendingUp, DollarSign, Activity, ArrowUp, ArrowDown } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

async function getAnalyticsData() {
  const now = new Date();
  const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
  const sixtyDaysAgo = new Date(now.getTime() - 60 * 24 * 60 * 60 * 1000);

  // Current period stats
  const currentPeriodUsers = await db.user.count({
    where: { createdAt: { gte: thirtyDaysAgo } },
  });

  // Previous period stats
  const previousPeriodUsers = await db.user.count({
    where: {
      createdAt: {
        gte: sixtyDaysAgo,
        lt: thirtyDaysAgo,
      },
    },
  });

  // Active subscriptions
  const currentSubscriptions = await db.user.count({
    where: {
      subscriptionStatus: 'active',
      subscriptionTier: { not: 'free' },
    },
  });

  // Total logins last 30 days
  const totalLogins = await db.loginHistory.count({
    where: {
      loginAt: { gte: thirtyDaysAgo },
      successful: true,
    },
  });

  // MRR using Stripe prices
  const prices = await getStripePrices();
  const proPlan = await db.user.count({
    where: { subscriptionTier: 'pro', subscriptionStatus: 'active' },
  });
  const enterprisePlan = await db.user.count({
    where: { subscriptionTier: 'enterprise', subscriptionStatus: 'active' },
  });
  const mrr = proPlan * prices.pro.monthly + enterprisePlan * prices.enterprise.monthly;

  // Calculate growth
  const userGrowth =
    previousPeriodUsers > 0
      ? ((currentPeriodUsers - previousPeriodUsers) / previousPeriodUsers) * 100
      : 0;

  return {
    currentPeriodUsers,
    previousPeriodUsers,
    userGrowth,
    currentSubscriptions,
    totalLogins,
    mrr,
  };
}

export default async function AdminAnalyticsPage() {
  const [analytics, currencySymbol] = await Promise.all([
    getAnalyticsData(),
    getCurrencySymbol(),
  ]);

  const isGrowthPositive = analytics.userGrowth > 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Analytics</h1>
        <p className="text-muted-foreground">Insights and metrics for your SaaS platform</p>
      </div>

      {/* Key Metrics */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">New Users</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{analytics.currentPeriodUsers}</div>
            <div className="mt-1 flex items-center text-xs">
              {isGrowthPositive ? (
                <ArrowUp className="mr-1 h-3 w-3 text-green-600" />
              ) : (
                <ArrowDown className="mr-1 h-3 w-3 text-red-600" />
              )}
              <span className={isGrowthPositive ? 'text-green-600' : 'text-red-600'}>
                {Math.abs(analytics.userGrowth).toFixed(1)}%
              </span>
              <span className="ml-1 text-muted-foreground">vs last period</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Subscriptions</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{analytics.currentSubscriptions}</div>
            <p className="mt-1 text-xs text-muted-foreground">Paying customers</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">MRR</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{currencySymbol}{analytics.mrr.toLocaleString()}</div>
            <p className="mt-1 text-xs text-muted-foreground">Monthly recurring revenue</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Logins</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{analytics.totalLogins}</div>
            <p className="mt-1 text-xs text-muted-foreground">Last 30 days</p>
          </CardContent>
        </Card>
      </div>

      {/* Detailed Analytics */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>User Growth</CardTitle>
            <CardDescription>New user sign-ups over time</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-center justify-between rounded-lg border p-4">
                <div>
                  <p className="text-sm font-medium">Current Period (30 days)</p>
                  <p className="mt-1 text-2xl font-bold">{analytics.currentPeriodUsers}</p>
                </div>
                <Badge variant={isGrowthPositive ? 'default' : 'destructive'}>
                  {isGrowthPositive ? '+' : ''}
                  {analytics.userGrowth.toFixed(1)}%
                </Badge>
              </div>

              <div className="flex items-center justify-between rounded-lg border p-4">
                <div>
                  <p className="text-sm font-medium">Previous Period (30 days)</p>
                  <p className="mt-1 text-2xl font-bold">{analytics.previousPeriodUsers}</p>
                </div>
                <Badge variant="outline">Comparison</Badge>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Revenue Metrics</CardTitle>
            <CardDescription>Subscription and revenue breakdown</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-center justify-between rounded-lg border p-4">
                <div>
                  <p className="text-sm font-medium">Monthly Recurring Revenue</p>
                  <p className="mt-1 text-2xl font-bold">{currencySymbol}{analytics.mrr.toLocaleString()}</p>
                </div>
                <TrendingUp className="h-8 w-8 text-primary" />
              </div>

              <div className="flex items-center justify-between rounded-lg border p-4">
                <div>
                  <p className="text-sm font-medium">Average Revenue Per User</p>
                  <p className="mt-1 text-2xl font-bold">
                    {currencySymbol}
                    {analytics.currentSubscriptions > 0
                      ? (analytics.mrr / analytics.currentSubscriptions).toFixed(2)
                      : '0'}
                  </p>
                </div>
                <DollarSign className="h-8 w-8 text-primary" />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Activity Overview */}
      <Card>
        <CardHeader>
          <CardTitle>Activity Overview</CardTitle>
          <CardDescription>Platform activity and engagement metrics</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">Total Logins</p>
              <p className="text-3xl font-bold">{analytics.totalLogins}</p>
              <p className="text-xs text-muted-foreground">Last 30 days</p>
            </div>

            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">Avg Logins/User</p>
              <p className="text-3xl font-bold">
                {analytics.currentPeriodUsers > 0
                  ? (analytics.totalLogins / analytics.currentPeriodUsers).toFixed(1)
                  : '0'}
              </p>
              <p className="text-xs text-muted-foreground">Engagement metric</p>
            </div>

            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">Conversion Rate</p>
              <p className="text-3xl font-bold">
                {analytics.currentPeriodUsers > 0
                  ? ((analytics.currentSubscriptions / analytics.currentPeriodUsers) * 100).toFixed(
                      1
                    )
                  : '0'}
                %
              </p>
              <p className="text-xs text-muted-foreground">Free to paid</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
