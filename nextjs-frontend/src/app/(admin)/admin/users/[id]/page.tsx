import { notFound } from 'next/navigation';
import Link from 'next/link';
import { KeyRound, Shield, ToggleLeft } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { StatusPill } from '@/components/ui/status-pill';
import { Panel } from '@/components/dashboard/overview/panel';
import { adminErrorMessage, fetchAdminUser, toAdminUserDetail } from '@/lib/api/admin-users';
import { logger } from '@/lib/logger';
import { InlineError } from '../../_components/inline-error';
import { formatAdminDate, formatAdminDateTime } from '../../_components/format-admin-date';

const USERS_HREF = '/admin/users';

function BackToUsers() {
  return (
    <Button variant="outline" asChild>
      <Link href={USERS_HREF}>Back to Users</Link>
    </Button>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 border-b border-border py-2 last:border-b-0">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words text-right font-medium">{children}</dd>
    </div>
  );
}

function ErrorState({ message, retryHref }: { message: string; retryHref: string }) {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-bold tracking-tight">User Details</h1>
        <BackToUsers />
      </div>
      <InlineError message={message} retryHref={retryHref} />
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
    return (
      <ErrorState
        message={adminErrorMessage(result)}
        retryHref={`${USERS_HREF}/${encodeURIComponent(id)}`}
      />
    );
  }

  const user = toAdminUserDetail(result.data);
  const lastLogin = user.lastLoginAt ? formatAdminDateTime(user.lastLoginAt) : '';
  const memberSince = formatAdminDate(user.createdAt);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">User Details</h1>
          <p className="text-muted-foreground">Viewing information for {user.email}</p>
        </div>
        <BackToUsers />
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Panel title="Basic Information" titleId="admin-user-basic">
          <dl>
            <Row label="Email">{user.email}</Row>
            <Row label="Display Name">{user.displayName || '—'}</Row>
            <Row label="User ID">
              <span className="break-all font-mono text-sm">{user.id}</span>
            </Row>
            <Row label="Email Verified">
              {user.emailVerified ? (
                <StatusPill variant="good">Verified</StatusPill>
              ) : (
                <StatusPill variant="warn">Unverified</StatusPill>
              )}
            </Row>
            <Row label="Two-factor">
              {user.twoFactorEnabled ? (
                <StatusPill variant="good">Enabled</StatusPill>
              ) : (
                <StatusPill variant="neutral" icon={ToggleLeft}>
                  Disabled
                </StatusPill>
              )}
            </Row>
            <Row label="Last Login">{lastLogin || '—'}</Row>
            <Row label="Member Since">{memberSince || '—'}</Row>
          </dl>
        </Panel>

        <Panel title="Profile" titleId="admin-user-profile">
          <dl>
            <Row label="Bio">{user.bio || '—'}</Row>
            <Row label="Location">{user.location || '—'}</Row>
            <Row label="Website">{user.website || '—'}</Row>
            <Row label="Phone">{user.phoneNumber || '—'}</Row>
          </dl>
        </Panel>
      </div>

      <Panel title="Admin Access" titleId="admin-user-access">
        <dl>
          <Row label="Admin Role">
            {user.isAdmin ? (
              <StatusPill variant="info" icon={Shield} className="capitalize">
                {(user.adminRole ?? 'admin').replaceAll('_', ' ')}
              </StatusPill>
            ) : (
              <span className="text-sm text-muted-foreground">None</span>
            )}
          </Row>
          {user.adminPermissions.length > 0 && (
            <Row label="Permissions">
              <ul aria-label="Permissions" className="flex flex-wrap justify-end gap-2">
                {user.adminPermissions.map((permission) => (
                  <li key={permission}>
                    <StatusPill variant="neutral" icon={KeyRound}>
                      {permission}
                    </StatusPill>
                  </li>
                ))}
              </ul>
            </Row>
          )}
        </dl>
      </Panel>
    </div>
  );
}
