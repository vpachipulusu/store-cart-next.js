import type { ReactNode } from 'react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card';
import { PermissionNotice } from '@/components/dashboard/overview/permission-notice';
import { InviteMemberForm } from '@/components/team/invite-member-form';
import {
  MEMBERS_PAGE_SIZE,
  canManageTeam,
  fetchTeam,
  resolveTeamOrganization,
} from '@/lib/api/team';
import { logger } from '@/lib/logger';

export const metadata = { title: 'Team' };

const LOAD_FAILED_MESSAGE = 'We could not load your team. Please try again.';

const ROLE_LABELS: Record<string, string> = { OWNER: 'Owner', ADMIN: 'Admin', STAFF: 'Staff' };

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

/** Card titles under the page h1 are h2 (CardTitle renders an h3). */
function SectionTitle({ children }: { children: ReactNode }) {
  return <h2 className="font-semibold leading-none tracking-tight">{children}</h2>;
}

function LoadError({ message }: { message: string }) {
  return (
    <Alert variant="destructive">
      <AlertTitle>Team unavailable</AlertTitle>
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}

/** Team settings (KAN-62): owners and admins see members, invite by email and see pending invitations. */
export default async function TeamSettingsPage() {
  const organization = await resolveTeamOrganization();
  if (!organization.success) {
    logger.error('Team page: organisation lookup failed', { status: organization.status });
    return <LoadError message={LOAD_FAILED_MESSAGE} />;
  }
  if (!organization.data) {
    return <LoadError message="Create a store first. Your team belongs to its organisation." />;
  }
  if (!canManageTeam(organization.data.role)) return <PermissionNotice />;

  const team = await fetchTeam();
  if (!team.success) {
    logger.error('Team page: load failed', { status: team.status });
    return <LoadError message={LOAD_FAILED_MESSAGE} />;
  }
  const { members, membersTruncated, invitations } = team.data;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl tracking-tight">Team</h1>
        <p className="text-muted-foreground">
          People who can work on {team.data.organization.name}. Owners and admins manage the team
          and billing; staff work on products and orders.
        </p>
      </header>

      <Card>
        <CardHeader>
          <SectionTitle>Invite a team member</SectionTitle>
          <CardDescription>
            We email them a link. It works once and expires after 7 days.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <InviteMemberForm />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <SectionTitle>Members</SectionTitle>
        </CardHeader>
        <CardContent>
          <ul className="divide-y divide-border" aria-label="Members">
            {members.map((member) => (
              <li
                key={member.user_id}
                className="flex flex-wrap items-center justify-between gap-2 py-3"
              >
                <div>
                  <p className="font-medium">{member.display_name || member.email}</p>
                  {member.display_name && (
                    <p className="text-sm text-muted-foreground">{member.email}</p>
                  )}
                </div>
                <Badge variant="outline">{ROLE_LABELS[member.role] ?? member.role}</Badge>
              </li>
            ))}
          </ul>
          {membersTruncated && (
            <p className="pt-3 text-sm text-muted-foreground">
              Showing the first {MEMBERS_PAGE_SIZE} members.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <SectionTitle>Pending invitations</SectionTitle>
        </CardHeader>
        <CardContent>
          {invitations.length === 0 ? (
            <p className="text-sm text-muted-foreground">No pending invitations.</p>
          ) : (
            <ul className="divide-y divide-border" aria-label="Pending invitations">
              {invitations.map((invitation) => (
                <li
                  key={invitation.id}
                  className="flex flex-wrap items-center justify-between gap-2 py-3"
                >
                  <div>
                    <p className="font-medium">{invitation.email}</p>
                    <p className="text-sm text-muted-foreground">
                      Expires {formatDate(invitation.expires_at)}
                    </p>
                  </div>
                  <Badge variant="outline">{ROLE_LABELS[invitation.role] ?? invitation.role}</Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
