import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { adminAuth } from '@/lib/firebase/admin';
import { db } from '@/lib/db/client';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  User,
  Mail,
  Calendar,
  Shield,
  Clock,
  Activity,
  TrendingUp,
  CreditCard,
  Bell,
  Settings,
  FileText,
  ArrowUpRight,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { SubscriptionSuccessHandler } from '@/components/dashboard/subscription-success-handler';
import { Suspense } from 'react';

// Disable caching for this page to ensure fresh subscription data
export const dynamic = 'force-dynamic';
export const revalidate = 0;

async function getUserData() {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get('session')?.value;

    if (!sessionCookie) {
      return null;
    }

    const decodedClaims = await adminAuth.verifySessionCookie(sessionCookie, true);

    const user = await db.user.findUnique({
      where: { firebaseUid: decodedClaims.uid },
      include: {
        settings: true,
        loginHistory: {
          orderBy: { loginAt: 'desc' },
          take: 5,
        },
        notifications: {
          where: { read: false },
          take: 10,
        },
      },
    });

    return user;
  } catch (error) {
    // Expired/invalid session — clear cookies via route handler and redirect to login
    redirect('/api/auth/clear-session');
  }
}

async function getStats(user: any) {
  const totalNotifications = await db.notification.count({
    where: { userId: user.id },
  });

  const unreadNotifications = await db.notification.count({
    where: { userId: user.id, read: false },
  });

  const totalLogins = await db.loginHistory.count({
    where: { userId: user.id, successful: true },
  });

  const accountAge = Math.floor(
    (Date.now() - new Date(user.createdAt).getTime()) / (1000 * 60 * 60 * 24)
  );

  return {
    totalNotifications,
    unreadNotifications,
    totalLogins,
    accountAge,
  };
}

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  // Await searchParams as per Next.js 15 requirements
  await searchParams;

  const user = await getUserData();

  if (!user) {
    redirect('/login');
  }

  const stats = await getStats(user);

  const isFreeTier = user.subscriptionTier === 'free';
  const hasActiveSubscription = user.subscriptionStatus === 'active' && !isFreeTier;

  return (
    <div className="space-y-8">
      {/* Subscription Success Handler */}
      <Suspense fallback={null}>
        <SubscriptionSuccessHandler />
      </Suspense>

      {/* Header */}
      <div>
        <h1 className="text-3xl tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">Welcome back, {user.displayName || user.email}!</p>
      </div>

      {/* Upgrade Banner for Free Tier */}
      {isFreeTier && (
        <Card className="theme-card border-theme-accent/30 bg-gradient-to-r from-theme-accent/[0.05] to-theme-accent/[0.02]">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <TrendingUp className="h-5 w-5 text-theme-accent" />
                  Upgrade to Pro
                </CardTitle>
                <CardDescription>Unlock premium features and remove limitations</CardDescription>
              </div>
              <Button asChild className="bg-theme-accent text-white hover:bg-theme-accent-dark">
                <Link href="/pricing">
                  Upgrade Now <ArrowUpRight className="ml-2 h-4 w-4" />
                </Link>
              </Button>
            </div>
          </CardHeader>
        </Card>
      )}

      {/* Stats Grid */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="theme-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Account Status</CardTitle>
            <Shield className="h-4 w-4 text-theme-accent/70" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {user.emailVerified ? (
                <Badge variant="default">Verified</Badge>
              ) : (
                <Badge variant="destructive">Unverified</Badge>
              )}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {user.emailVerified ? 'Email verified' : 'Please verify your email'}
            </p>
          </CardContent>
        </Card>

        <Card className="theme-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Subscription Plan</CardTitle>
            <CreditCard className="h-4 w-4 text-theme-accent/70" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold capitalize">{user.subscriptionTier}</div>
            <p className="mt-1 text-xs text-muted-foreground">
              {hasActiveSubscription
                ? `Active until ${new Date(user.stripeCurrentPeriodEnd!).toLocaleDateString()}`
                : user.subscriptionStatus}
            </p>
          </CardContent>
        </Card>

        <Card className="theme-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Notifications</CardTitle>
            <Bell className="h-4 w-4 text-theme-accent/70" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.unreadNotifications}</div>
            <p className="mt-1 text-xs text-muted-foreground">
              {stats.unreadNotifications === 1 ? 'Unread notification' : 'Unread notifications'}
            </p>
          </CardContent>
        </Card>

        <Card className="theme-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Logins</CardTitle>
            <Activity className="h-4 w-4 text-theme-accent/70" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.totalLogins}</div>
            <p className="mt-1 text-xs text-muted-foreground">Successful logins</p>
          </CardContent>
        </Card>
      </div>

      {/* Quick Actions Grid */}
      <div>
        <h2 className="mb-4 text-2xl font-bold tracking-tight">Quick Actions</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card className="theme-card cursor-pointer transition-colors hover:bg-accent">
            <Link href="/dashboard/profile">
              <CardHeader>
                <div className="flex items-center gap-3">
                  <div className="rounded-lg bg-theme-accent/[0.08] p-2">
                    <User className="h-6 w-6 text-theme-accent" />
                  </div>
                  <div>
                    <CardTitle className="text-base">Edit Profile</CardTitle>
                    <CardDescription className="text-xs">Update your details</CardDescription>
                  </div>
                </div>
              </CardHeader>
            </Link>
          </Card>

          <Card className="theme-card cursor-pointer transition-colors hover:bg-accent">
            <Link href="/dashboard/settings">
              <CardHeader>
                <div className="flex items-center gap-3">
                  <div className="rounded-lg bg-theme-accent/[0.08] p-2">
                    <Settings className="h-6 w-6 text-theme-accent" />
                  </div>
                  <div>
                    <CardTitle className="text-base">Settings</CardTitle>
                    <CardDescription className="text-xs">Configure preferences</CardDescription>
                  </div>
                </div>
              </CardHeader>
            </Link>
          </Card>

          <Card className="theme-card cursor-pointer transition-colors hover:bg-accent">
            <Link href="/dashboard/security">
              <CardHeader>
                <div className="flex items-center gap-3">
                  <div className="rounded-lg bg-theme-accent/[0.08] p-2">
                    <Shield className="h-6 w-6 text-theme-accent" />
                  </div>
                  <div>
                    <CardTitle className="text-base">Security</CardTitle>
                    <CardDescription className="text-xs">Manage account security</CardDescription>
                  </div>
                </div>
              </CardHeader>
            </Link>
          </Card>

          <Card className="theme-card cursor-pointer transition-colors hover:bg-accent">
            <Link href="/dashboard/settings/billing">
              <CardHeader>
                <div className="flex items-center gap-3">
                  <div className="rounded-lg bg-theme-accent/[0.08] p-2">
                    <CreditCard className="h-6 w-6 text-theme-accent" />
                  </div>
                  <div>
                    <CardTitle className="text-base">Billing</CardTitle>
                    <CardDescription className="text-xs">Manage subscription</CardDescription>
                  </div>
                </div>
              </CardHeader>
            </Link>
          </Card>
        </div>
      </div>

      {/* Account Overview and Activity */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Account Information */}
        <Card className="theme-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <User className="h-5 w-5" />
              Account Information
            </CardTitle>
            <CardDescription>Your personal details</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-3">
              <div className="flex items-center justify-between border-b py-2">
                <div className="flex items-center gap-2 text-sm">
                  <Mail className="h-4 w-4 text-muted-foreground" />
                  <span className="text-muted-foreground">Email</span>
                </div>
                <span className="text-sm font-medium">{user.email}</span>
              </div>

              <div className="flex items-center justify-between border-b py-2">
                <div className="flex items-center gap-2 text-sm">
                  <User className="h-4 w-4 text-muted-foreground" />
                  <span className="text-muted-foreground">Name</span>
                </div>
                <span className="text-sm font-medium">{user.displayName || 'Not set'}</span>
              </div>

              <div className="flex items-center justify-between border-b py-2">
                <div className="flex items-center gap-2 text-sm">
                  <Calendar className="h-4 w-4 text-muted-foreground" />
                  <span className="text-muted-foreground">Member Since</span>
                </div>
                <span className="text-sm font-medium">
                  {new Date(user.createdAt).toLocaleDateString()}
                </span>
              </div>

              <div className="flex items-center justify-between py-2">
                <div className="flex items-center gap-2 text-sm">
                  <Clock className="h-4 w-4 text-muted-foreground" />
                  <span className="text-muted-foreground">Last Login</span>
                </div>
                <span className="text-sm font-medium">
                  {user.lastLoginAt ? new Date(user.lastLoginAt).toLocaleString() : 'Never'}
                </span>
              </div>
            </div>

            <Separator />

            <Button asChild className="w-full">
              <Link href="/dashboard/profile">
                Edit Profile <ArrowUpRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </CardContent>
        </Card>

        {/* Recent Login Activity */}
        <Card className="theme-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5" />
              Recent Activity
            </CardTitle>
            <CardDescription>Your last 5 login sessions</CardDescription>
          </CardHeader>
          <CardContent>
            {user.loginHistory && user.loginHistory.length > 0 ? (
              <div className="space-y-3">
                {user.loginHistory.map((login: any) => (
                  <div
                    key={login.id}
                    className="flex items-start justify-between border-b pb-3 last:border-0 last:pb-0"
                  >
                    <div className="space-y-1">
                      <p className="text-sm font-medium">
                        {new Date(login.loginAt).toLocaleDateString()} at{' '}
                        {new Date(login.loginAt).toLocaleTimeString()}
                      </p>
                      <div className="flex items-center gap-2">
                        <p className="text-xs text-muted-foreground">
                          {login.ipAddress || 'Unknown IP'}
                        </p>
                        {login.location && (
                          <>
                            <span className="text-xs text-muted-foreground">•</span>
                            <p className="text-xs text-muted-foreground">{login.location}</p>
                          </>
                        )}
                      </div>
                    </div>
                    <Badge
                      variant={login.successful ? 'default' : 'destructive'}
                      className="shrink-0"
                    >
                      {login.successful ? 'Success' : 'Failed'}
                    </Badge>
                  </div>
                ))}
              </div>
            ) : (
              <p className="py-4 text-center text-sm text-muted-foreground">
                No login history available
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Notifications Feed */}
      {user.notifications && user.notifications.length > 0 && (
        <Card className="theme-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bell className="h-5 w-5" />
              Recent Notifications
            </CardTitle>
            <CardDescription>
              You have {stats.unreadNotifications} unread notifications
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {user.notifications.map((notification: any) => (
                <div
                  key={notification.id}
                  className="flex items-start gap-3 rounded-lg border bg-card p-3"
                >
                  <div className="rounded-full bg-theme-accent/[0.08] p-2">
                    <Bell className="h-4 w-4 text-theme-accent" />
                  </div>
                  <div className="flex-1 space-y-1">
                    <p className="text-sm font-medium leading-none">{notification.title}</p>
                    <p className="text-sm text-muted-foreground">{notification.message}</p>
                    <p className="text-xs text-muted-foreground">
                      {new Date(notification.createdAt).toLocaleString()}
                    </p>
                  </div>
                  {notification.link && (
                    <Button asChild variant="ghost" size="sm">
                      <Link href={notification.link}>View</Link>
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Account Stats Summary */}
      <Card className="theme-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            Account Summary
          </CardTitle>
          <CardDescription>Overview of your account metrics</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">Account Age</p>
              <p className="text-2xl font-bold">{stats.accountAge}</p>
              <p className="text-xs text-muted-foreground">Days</p>
            </div>
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">Total Logins</p>
              <p className="text-2xl font-bold">{stats.totalLogins}</p>
              <p className="text-xs text-muted-foreground">Successful</p>
            </div>
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">Notifications</p>
              <p className="text-2xl font-bold">{stats.totalNotifications}</p>
              <p className="text-xs text-muted-foreground">{stats.unreadNotifications} unread</p>
            </div>
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">Current Plan</p>
              <p className="text-2xl font-bold capitalize">{user.subscriptionTier}</p>
              <p className="text-xs text-muted-foreground">{user.subscriptionStatus}</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
