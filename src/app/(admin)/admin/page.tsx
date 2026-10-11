import { db } from '@/lib/db/client';
import { getStripePrices, getCurrencySymbol } from '@/config/subscriptions';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Users,
  CreditCard,
  TrendingUp,
  Activity,
  DollarSign,
  UserPlus,
  UserX,
  AlertCircle,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import Link from 'next/link';
import { Button } from '@/components/ui/button';

async function getAdminStats() {
  // Total users
  const totalUsers = await db.user.count();

  // New users (last 30 days)
  const thirtyDaysAgo = new Date();
  thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

  const newUsers = await db.user.count({
    where: {
      createdAt: {
        gte: thirtyDaysAgo,
      },
    },
  });

  // Active subscriptions
  const activeSubscriptions = await db.user.count({
    where: {
      subscriptionStatus: 'active',
      subscriptionTier: {
        not: 'free',
      },
    },
  });

  // Cancelled subscriptions (last 30 days)
  const cancelledSubscriptions = await db.user.count({
    where: {
      subscriptionStatus: 'canceled',
      updatedAt: {
        gte: thirtyDaysAgo,
      },
    },
  });

  // Recent users
  const recentUsers = await db.user.findMany({
    take: 10,
    orderBy: {
      createdAt: 'desc',
    },
    select: {
      id: true,
      email: true,
      displayName: true,
      createdAt: true,
      subscriptionTier: true,
      emailVerified: true,
    },
  });

  // Recent audit logs
  const recentLogs = await db.auditLog.findMany({
    take: 10,
    orderBy: {
      createdAt: 'desc',
    },
  });

  // Subscription breakdown
  const subscriptionBreakdown = await db.user.groupBy({
    by: ['subscriptionTier'],
    _count: true,
  });

  // Calculate MRR (Monthly Recurring Revenue) using Stripe prices
  const prices = await getStripePrices();
  const proPlan = await db.user.count({
    where: { subscriptionTier: 'pro', subscriptionStatus: 'active' },
  });
  const enterprisePlan = await db.user.count({
    where: { subscriptionTier: 'enterprise', subscriptionStatus: 'active' },
  });

  const mrr = proPlan * prices.pro.monthly + enterprisePlan * prices.enterprise.monthly;

  return {
    totalUsers,
    newUsers,
    activeSubscriptions,
    cancelledSubscriptions,
    recentUsers,
    recentLogs,
    subscriptionBreakdown,
    mrr,
  };
}

export default async function AdminDashboardPage() {
  const [stats, currencySymbol] = await Promise.all([
    getAdminStats(),
    getCurrencySymbol(),
  ]);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl tracking-tight">Admin Dashboard</h1>
        <p className="text-muted-foreground">Monitor and manage your SaaS platform</p>
      </div>

      {/* Key Metrics */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="theme-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Users</CardTitle>
            <Users className="h-4 w-4 text-theme-accent/70" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.totalUsers}</div>
            <p className="text-xs text-muted-foreground">+{stats.newUsers} in last 30 days</p>
          </CardContent>
        </Card>

        <Card className="theme-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Subscriptions</CardTitle>
            <CreditCard className="h-4 w-4 text-theme-accent/70" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.activeSubscriptions}</div>
            <p className="text-xs text-muted-foreground">
              {stats.cancelledSubscriptions} cancelled this month
            </p>
          </CardContent>
        </Card>

        <Card className="theme-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">MRR</CardTitle>
            <DollarSign className="h-4 w-4 text-theme-accent/70" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-theme-accent">{currencySymbol}{stats.mrr.toLocaleString()}</div>
            <p className="text-xs text-muted-foreground">Monthly recurring revenue</p>
          </CardContent>
        </Card>

        <Card className="theme-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">New Users</CardTitle>
            <UserPlus className="h-4 w-4 text-theme-accent/70" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.newUsers}</div>
            <p className="text-xs text-muted-foreground">Last 30 days</p>
          </CardContent>
        </Card>
      </div>

      {/* Subscription Breakdown */}
      <Card>
        <CardHeader>
          <CardTitle>Subscription Breakdown</CardTitle>
          <CardDescription>Users by subscription tier</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-3">
            {stats.subscriptionBreakdown.map((sub: any) => (
              <div
                key={sub.subscriptionTier}
                className="flex items-center justify-between rounded-lg border p-4"
              >
                <div>
                  <p className="text-sm font-medium capitalize">{sub.subscriptionTier}</p>
                  <p className="text-2xl font-bold">{sub._count}</p>
                </div>
                <Badge variant="secondary">
                  {((sub._count / stats.totalUsers) * 100).toFixed(1)}%
                </Badge>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Recent Users and Activity */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Recent Users */}
        <Card>
          <CardHeader>
            <CardTitle>Recent Users</CardTitle>
            <CardDescription>Latest user registrations</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {stats.recentUsers.map((user: any) => (
                <div
                  key={user.id}
                  className="flex items-center justify-between border-b pb-3 last:border-0"
                >
                  <div className="space-y-1">
                    <p className="text-sm font-medium">{user.displayName || user.email}</p>
                    <p className="text-xs text-muted-foreground">
                      {new Date(user.createdAt).toLocaleDateString()} • {user.subscriptionTier}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {user.emailVerified ? (
                      <Badge variant="default">Verified</Badge>
                    ) : (
                      <Badge variant="secondary">Pending</Badge>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4">
              <Button asChild variant="outline" className="w-full">
                <Link href="/admin/users">View All Users</Link>
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Recent Activity */}
        <Card>
          <CardHeader>
            <CardTitle>Recent Activity</CardTitle>
            <CardDescription>Latest audit log entries</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {stats.recentLogs.length > 0 ? (
                stats.recentLogs.map((log: any) => (
                  <div key={log.id} className="flex items-start gap-3 border-b pb-3 last:border-0">
                    <div className="rounded-full bg-primary/10 p-2">
                      <Activity className="h-3 w-3 text-primary" />
                    </div>
                    <div className="flex-1 space-y-1">
                      <p className="text-sm font-medium">{log.action}</p>
                      <p className="text-xs text-muted-foreground">
                        {log.resource} • {new Date(log.createdAt).toLocaleString()}
                      </p>
                    </div>
                  </div>
                ))
              ) : (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  No activity logged yet
                </p>
              )}
            </div>
            <div className="mt-4">
              <Button asChild variant="outline" className="w-full">
                <Link href="/admin/audit-logs">View All Logs</Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Quick Actions */}
      <Card>
        <CardHeader>
          <CardTitle>Quick Actions</CardTitle>
          <CardDescription>Common administrative tasks</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Button asChild variant="outline">
              <Link href="/admin/users">
                <Users className="mr-2 h-4 w-4" />
                Manage Users
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/admin/subscriptions">
                <CreditCard className="mr-2 h-4 w-4" />
                Subscriptions
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/admin/analytics">
                <TrendingUp className="mr-2 h-4 w-4" />
                Analytics
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/admin/settings">
                <Activity className="mr-2 h-4 w-4" />
                Settings
              </Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
