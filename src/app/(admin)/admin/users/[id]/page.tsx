import { db } from '@/lib/db/client';
import { notFound } from 'next/navigation';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { User, Mail, Calendar, Shield, CreditCard, Activity, Settings } from 'lucide-react';
import Link from 'next/link';

async function getUserDetails(userId: string) {
  const user = await db.user.findUnique({
    where: { id: userId },
    include: {
      adminUser: true,
      settings: true,
      loginHistory: {
        orderBy: { loginAt: 'desc' },
        take: 10,
      },
      notifications: {
        orderBy: { createdAt: 'desc' },
        take: 10,
      },
    },
  });

  if (!user) {
    notFound();
  }

  return user;
}

export default async function AdminUserDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getUserDetails(id);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">User Details</h1>
          <p className="text-muted-foreground">Viewing information for {user.email}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" asChild>
            <Link href="/admin/users">Back to Users</Link>
          </Button>
          <Button variant="destructive">Suspend User</Button>
        </div>
      </div>

      {/* User Info Grid */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Basic Information */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <User className="h-5 w-5" />
              Basic Information
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between border-b py-2">
              <span className="text-sm text-muted-foreground">Email</span>
              <span className="font-medium">{user.email}</span>
            </div>

            <div className="flex items-center justify-between border-b py-2">
              <span className="text-sm text-muted-foreground">Display Name</span>
              <span className="font-medium">{user.displayName || '—'}</span>
            </div>

            <div className="flex items-center justify-between border-b py-2">
              <span className="text-sm text-muted-foreground">User ID</span>
              <span className="font-mono text-sm">{user.id}</span>
            </div>

            <div className="flex items-center justify-between border-b py-2">
              <span className="text-sm text-muted-foreground">Firebase UID</span>
              <span className="font-mono text-sm">{user.firebaseUid}</span>
            </div>

            <div className="flex items-center justify-between border-b py-2">
              <span className="text-sm text-muted-foreground">Email Verified</span>
              {user.emailVerified ? (
                <Badge variant="default">Verified</Badge>
              ) : (
                <Badge variant="destructive">Unverified</Badge>
              )}
            </div>

            <div className="flex items-center justify-between py-2">
              <span className="text-sm text-muted-foreground">Member Since</span>
              <span className="font-medium">{new Date(user.createdAt).toLocaleDateString()}</span>
            </div>
          </CardContent>
        </Card>

        {/* Subscription Info */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CreditCard className="h-5 w-5" />
              Subscription Information
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between border-b py-2">
              <span className="text-sm text-muted-foreground">Plan</span>
              <Badge className="capitalize">{user.subscriptionTier}</Badge>
            </div>

            <div className="flex items-center justify-between border-b py-2">
              <span className="text-sm text-muted-foreground">Status</span>
              <Badge
                variant={user.subscriptionStatus === 'active' ? 'default' : 'secondary'}
                className="capitalize"
              >
                {user.subscriptionStatus}
              </Badge>
            </div>

            <div className="flex items-center justify-between border-b py-2">
              <span className="text-sm text-muted-foreground">Stripe Customer ID</span>
              <span className="font-mono text-sm">{user.stripeCustomerId || '—'}</span>
            </div>

            <div className="flex items-center justify-between border-b py-2">
              <span className="text-sm text-muted-foreground">Current Period End</span>
              <span className="font-medium">
                {user.stripeCurrentPeriodEnd
                  ? new Date(user.stripeCurrentPeriodEnd).toLocaleDateString()
                  : '—'}
              </span>
            </div>

            <div className="flex items-center justify-between py-2">
              <span className="text-sm text-muted-foreground">Admin Role</span>
              {user.adminUser ? (
                <Badge variant="destructive" className="capitalize">
                  {user.adminUser.role.replace('_', ' ')}
                </Badge>
              ) : (
                <span className="text-sm text-muted-foreground">None</span>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Activity Sections */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Login History */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5" />
              Login History
            </CardTitle>
            <CardDescription>Recent login activity</CardDescription>
          </CardHeader>
          <CardContent>
            {user.loginHistory.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead>IP Address</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {user.loginHistory.map((login: any) => (
                    <TableRow key={login.id}>
                      <TableCell className="text-sm">
                        {new Date(login.loginAt).toLocaleString()}
                      </TableCell>
                      <TableCell className="font-mono text-sm">{login.ipAddress || '—'}</TableCell>
                      <TableCell>
                        <Badge variant={login.successful ? 'default' : 'destructive'}>
                          {login.successful ? 'Success' : 'Failed'}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="py-4 text-center text-sm text-muted-foreground">No login history</p>
            )}
          </CardContent>
        </Card>

        {/* Notifications */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Mail className="h-5 w-5" />
              Notifications
            </CardTitle>
            <CardDescription>Recent notifications</CardDescription>
          </CardHeader>
          <CardContent>
            {user.notifications.length > 0 ? (
              <div className="space-y-3">
                {user.notifications.map((notification: any) => (
                  <div key={notification.id} className="space-y-1 rounded-lg border p-3">
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-medium">{notification.title}</p>
                      <Badge variant={notification.read ? 'secondary' : 'default'}>
                        {notification.read ? 'Read' : 'Unread'}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground">{notification.message}</p>
                    <p className="text-xs text-muted-foreground">
                      {new Date(notification.createdAt).toLocaleString()}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="py-4 text-center text-sm text-muted-foreground">No notifications</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* User Settings */}
      {user.settings && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Settings className="h-5 w-5" />
              User Settings
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Theme</p>
                <p className="font-medium capitalize">{user.settings.theme}</p>
              </div>

              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Language</p>
                <p className="font-medium uppercase">{user.settings.language}</p>
              </div>

              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Timezone</p>
                <p className="font-medium">{user.settings.timezone}</p>
              </div>

              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Email Notifications</p>
                <Badge variant={user.settings.emailNotifications ? 'default' : 'secondary'}>
                  {user.settings.emailNotifications ? 'Enabled' : 'Disabled'}
                </Badge>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
