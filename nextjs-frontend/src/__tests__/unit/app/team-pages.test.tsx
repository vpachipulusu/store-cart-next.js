// @vitest-environment node
/**
 * KAN-62: the team settings page, the billing STAFF gate and the public invitation page. Server components are
 * rendered to static markup with the API wrappers mocked.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

const mocks = vi.hoisted(() => ({
  resolveTeamOrganization: vi.fn(),
  isStaffOnlyMember: vi.fn(),
  fetchTeam: vi.fn(),
  getVerifiedSessionClaims: vi.fn(),
  logError: vi.fn(),
}));

vi.mock('@/lib/api/team', () => ({
  MEMBERS_PAGE_SIZE: 100,
  canManageTeam: (role: string) => role === 'OWNER' || role === 'ADMIN',
  resolveTeamOrganization: mocks.resolveTeamOrganization,
  isStaffOnlyMember: mocks.isStaffOnlyMember,
  fetchTeam: mocks.fetchTeam,
}));
vi.mock('@/lib/auth/verified-session', () => ({
  getVerifiedSessionClaims: mocks.getVerifiedSessionClaims,
  isEmailNotVerifiedError: (error: unknown) =>
    error instanceof Error && error.name === 'EmailNotVerifiedError',
}));
vi.mock('@/lib/logger', () => ({ logger: { error: mocks.logError } }));
vi.mock('@/components/team/invite-member-form', () => ({
  InviteMemberForm: () => <form data-testid="invite-form" />,
}));
vi.mock('@/components/team/accept-invitation-button', () => ({
  AcceptInvitationButton: ({ token }: { token: string }) => (
    <button data-token={token}>Accept</button>
  ),
}));

import TeamSettingsPage from '@/app/dashboard/settings/team/page';
import BillingSettingsLayout from '@/app/dashboard/settings/billing/layout';
import InvitePage, { metadata as inviteMetadata } from '@/app/invite/[token]/page';

const html = (node: React.ReactNode) => renderToStaticMarkup(node as React.ReactElement);
const NOTICE = 'You do not have access';
const org = (role: string) => ({ success: true, data: { id: 'org-a', name: 'Acme', role } });

const TEAM = {
  success: true,
  data: {
    organization: { id: 'org-a', name: 'Acme', role: 'OWNER' },
    members: [
      {
        user_id: 'u1',
        email: 'owner@example.com',
        display_name: 'Olive Owner',
        role: 'OWNER',
        joined_at: '2026-10-01T00:00:00Z',
      },
      {
        user_id: 'u2',
        email: 'staff@example.com',
        display_name: null,
        role: 'STAFF',
        joined_at: '2026-10-02T00:00:00Z',
      },
    ],
    membersTruncated: false,
    invitations: [
      {
        id: 'inv1',
        email: 'new@example.com',
        role: 'ADMIN',
        expires_at: '2026-11-01T12:00:00Z',
        created_at: '2026-10-25T12:00:00Z',
      },
    ],
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.resolveTeamOrganization.mockResolvedValue(org('OWNER'));
  mocks.fetchTeam.mockResolvedValue(TEAM);
});

describe('team settings page', () => {
  it.each(['OWNER', 'ADMIN'])(
    'shows members, the invite form and pending invitations to %s',
    async (role) => {
      mocks.resolveTeamOrganization.mockResolvedValue(org(role));

      const markup = html(await TeamSettingsPage());

      expect(markup).toContain('Olive Owner');
      expect(markup).toContain('owner@example.com');
      expect(markup).toContain('staff@example.com');
      expect(markup).toContain('data-testid="invite-form"');
      expect(markup).toContain('new@example.com');
      expect(markup).toContain('Expires 1 Nov 2026');
      expect(markup).toMatch(/<h2[^>]*>Members<\/h2>/);
      expect(markup).not.toContain('<h3');
      expect(markup).not.toContain('Showing the first');
      expect(markup).not.toContain(NOTICE);
    }
  );

  it('shows the permission notice to STAFF without loading the team', async () => {
    mocks.resolveTeamOrganization.mockResolvedValue(org('STAFF'));

    const markup = html(await TeamSettingsPage());

    expect(markup).toContain(NOTICE);
    expect(markup).not.toContain('invite-form');
    expect(mocks.fetchTeam).not.toHaveBeenCalled();
  });

  it('says when the member list is cut at one page', async () => {
    mocks.fetchTeam.mockResolvedValue({ ...TEAM, data: { ...TEAM.data, membersTruncated: true } });

    expect(html(await TeamSettingsPage())).toContain('Showing the first 100 members.');
  });

  it('says when there are no pending invitations', async () => {
    mocks.fetchTeam.mockResolvedValue({ ...TEAM, data: { ...TEAM.data, invitations: [] } });

    expect(html(await TeamSettingsPage())).toContain('No pending invitations.');
  });

  it('asks for a store first when there is no organisation', async () => {
    mocks.resolveTeamOrganization.mockResolvedValue({ success: true, data: null });

    expect(html(await TeamSettingsPage())).toContain('Create a store first');
  });

  it('shows a curated error when the organisation or the team cannot be loaded', async () => {
    mocks.resolveTeamOrganization.mockResolvedValueOnce({
      success: false,
      error: 'SECRET',
      status: 500,
    });
    const first = html(await TeamSettingsPage());
    mocks.fetchTeam.mockResolvedValueOnce({ success: false, error: 'SECRET', status: 502 });
    const second = html(await TeamSettingsPage());

    for (const markup of [first, second]) {
      expect(markup).toContain('We could not load your team. Please try again.');
      expect(markup).not.toContain('SECRET');
    }
    expect(mocks.logError).toHaveBeenCalledTimes(2);
  });
});

describe('billing settings STAFF gate', () => {
  const child = <p>billing page</p>;

  it('shows the permission notice to a STAFF-only member', async () => {
    mocks.isStaffOnlyMember.mockResolvedValue({ success: true, data: true });

    const markup = html(await BillingSettingsLayout({ children: child }));

    expect(markup).toContain(NOTICE);
    expect(markup).not.toContain('billing page');
  });

  it.each([
    ['someone who manages an organisation', { success: true, data: false }],
    ['a failed lookup', { success: false, error: 'x' }],
  ])('renders the billing page for %s', async (_label, resolved) => {
    mocks.isStaffOnlyMember.mockResolvedValue(resolved);

    expect(html(await BillingSettingsLayout({ children: child }))).toContain('billing page');
  });
});

describe('invitation page', () => {
  const TOKEN = 'AbC_def-1234567890ghijklmnop';
  const params = Promise.resolve({ token: TOKEN });

  it('sends no referrer and is not indexed', () => {
    expect(inviteMetadata.referrer).toBe('no-referrer');
    expect(inviteMetadata.robots).toEqual({ index: false, follow: false });
  });

  it('shows the Accept button to a signed-in user', async () => {
    mocks.getVerifiedSessionClaims.mockResolvedValue({
      uid: 'fb-1',
      email: 'new@example.com',
      email_verified: true,
    });

    const markup = html(await InvitePage({ params }));

    expect(markup).toContain('new@example.com');
    expect(markup).toContain(`data-token="${TOKEN}"`);
  });

  it('tells a signed-out visitor to sign in and reopen the link', async () => {
    mocks.getVerifiedSessionClaims.mockResolvedValue(null);

    const markup = html(await InvitePage({ params }));

    expect(markup).toContain('then open this invitation link again');
    expect(markup).toContain('href="/login"');
    expect(markup).not.toContain('data-token');
  });

  it('clears an expired session before signing in again', async () => {
    mocks.getVerifiedSessionClaims.mockRejectedValue(
      Object.assign(new Error('Invalid session'), { code: 'auth/invalid-session-cookie' })
    );

    const markup = html(await InvitePage({ params }));

    expect(markup).toContain('Your session has expired');
    expect(markup).toContain('href="/api/auth/clear-session"');
    expect(markup).not.toContain('data-token');
  });

  it('does not sign anyone out during a backend outage', async () => {
    mocks.getVerifiedSessionClaims.mockRejectedValue(new Error('Session status check failed'));

    const markup = html(await InvitePage({ params }));

    expect(markup).toContain('We could not check your sign-in right now');
    expect(markup).not.toContain('clear-session');
    expect(markup).not.toContain('data-token');
  });

  it('asks an unverified user to verify their email first', async () => {
    mocks.getVerifiedSessionClaims.mockRejectedValue(
      Object.assign(new Error('unverified'), { name: 'EmailNotVerifiedError' })
    );

    const markup = html(await InvitePage({ params }));

    expect(markup).toContain('Verify your email address first');
    expect(markup).toContain('href="/verify-email"');
    expect(markup).not.toContain('data-token');
  });
});
