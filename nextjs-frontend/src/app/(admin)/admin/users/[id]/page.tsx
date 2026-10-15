import { notFound } from 'next/navigation';
import Link from 'next/link';
import { User, Shield, Phone } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { adminErrorMessage, fetchAdminUser, toAdminUserDetail } from '@/lib/api/admin-users';
import { logger } from '@/lib/logger';

function Row({
  label,
  children,
  last = false,
}: {
  label: string;
  children: React.ReactNode;
  last?: boolean;
}) {
  return (
    <div className={`flex items-center justify-between py-2 ${last ? '' : 'border-b'}`}>
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="font-medium">{children}</span>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold tracking-tight">User Details</h1>
      <p role="alert" className="text-destructive">
        {message}
      </p>
      <Button variant="outline" asChild>
        <Link href="/admin/users">Back to Users</Link>
      </Button>
    </div>
  );
}

export default async function AdminUserDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const result = await fetchAdminUser(id);

  if (!result.success) {
    if (result.status === 404 || result.status === 422) {
      notFound();
    }
    logger.error('Admin user page: read failed', { status: result.status });
    return <ErrorState message={adminErrorMessage(result)} />;
  }

  const user = toAdminUserDetail(result.data);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">User Details</h1>
          <p className="text-muted-foreground">Viewing information for {user.email}</p>
        </div>
        <Button variant="outline" asChild>
          <Link href="/admin/users">Back to Users</Link>
        </Button>
      </div>

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
            <Row label="Email">{user.email}</Row>
            <Row label="Display Name">{user.displayName || '—'}</Row>
            <Row label="User ID">
              <span className="font-mono text-sm">{user.id}</span>
            </Row>
            <Row label="Email Verified">
              {user.emailVerified ? (
                <Badge variant="default">Verified</Badge>
              ) : (
                <Badge variant="destructive">Unverified</Badge>
              )}
            </Row>
            <Row label="Two-factor">
              <Badge variant={user.twoFactorEnabled ? 'default' : 'secondary'}>
                {user.twoFactorEnabled ? 'Enabled' : 'Disabled'}
              </Badge>
            </Row>
            <Row label="Last Login">
              {user.lastLoginAt ? new Date(user.lastLoginAt).toLocaleString() : '—'}
            </Row>
            <Row label="Member Since" last>
              {new Date(user.createdAt).toLocaleDateString()}
            </Row>
          </CardContent>
        </Card>

        {/* Profile */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Phone className="h-5 w-5" />
              Profile
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Row label="Bio">{user.bio || '—'}</Row>
            <Row label="Location">{user.location || '—'}</Row>
            <Row label="Website">{user.website || '—'}</Row>
            <Row label="Phone" last>
              {user.phoneNumber || '—'}
            </Row>
          </CardContent>
        </Card>
      </div>

      {/* Admin access */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="h-5 w-5" />
            Admin Access
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Row label="Admin Role" last={user.adminPermissions.length === 0}>
            {user.isAdmin ? (
              <Badge variant="destructive" className="capitalize">
                {(user.adminRole ?? 'admin').replace('_', ' ')}
              </Badge>
            ) : (
              <span className="text-sm text-muted-foreground">None</span>
            )}
          </Row>
          {user.adminPermissions.length > 0 && (
            <div className="flex flex-wrap gap-2 py-2">
              {user.adminPermissions.map((permission) => (
                <Badge key={permission} variant="secondary">
                  {permission}
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
