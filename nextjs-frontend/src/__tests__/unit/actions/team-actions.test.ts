// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  createTeamInvitation: vi.fn(),
  acceptTeamInvitation: vi.fn(),
  getVerifiedUserId: vi.fn(),
  revalidatePath: vi.fn(),
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

vi.mock('next/headers', () => ({ cookies: vi.fn(), headers: vi.fn() }));
vi.mock('next/cache', () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock('@/lib/auth/verified-session', () => ({ getVerifiedUserId: mocks.getVerifiedUserId }));
vi.mock('@/lib/logger', () => ({ logger: mocks.logger }));
vi.mock('@/lib/stores/current', () => ({ getCurrentStoreSelection: vi.fn() }));
vi.mock('@/lib/api/team', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/team')>()),
  createTeamInvitation: mocks.createTeamInvitation,
  acceptTeamInvitation: mocks.acceptTeamInvitation,
}));

import { acceptInvitationAction, inviteTeamMemberAction } from '@/app/actions/team-actions';
import { NO_TEAM_ORGANIZATION_MESSAGE } from '@/lib/api/team';

const TOKEN = 'AbC_def-1234567890ghijklmnop';
const LINK = `https://app.test/invite/${TOKEN}`;

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getVerifiedUserId.mockResolvedValue('user-1');
  mocks.createTeamInvitation.mockResolvedValue({
    success: true,
    data: {
      id: 'inv1',
      email: 'new@example.com',
      role: 'STAFF',
      expires_at: '2026-11-01T00:00:00Z',
      created_at: '2026-10-25T00:00:00Z',
      accept_url: LINK,
      email_sent: false,
    },
  });
  mocks.acceptTeamInvitation.mockResolvedValue({
    success: true,
    data: { organization_id: 'org-a', role: 'ADMIN' },
  });
});

function logged(): string {
  return JSON.stringify([
    mocks.logger.info.mock.calls,
    mocks.logger.warn.mock.calls,
    mocks.logger.error.mock.calls,
  ]);
}

describe('inviteTeamMemberAction', () => {
  it('creates the invitation and returns the link once', async () => {
    const result = await inviteTeamMemberAction({ email: ' New@Example.com ', role: 'STAFF' });

    expect(result).toEqual({
      success: true,
      data: { email: 'new@example.com', acceptUrl: LINK, emailSent: false },
    });
    expect(mocks.createTeamInvitation).toHaveBeenCalledWith('New@Example.com', 'STAFF');
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/dashboard/settings/team');
  });

  it.each([
    [{ email: 'not-an-email', role: 'STAFF' }, 'Enter a valid email address.'],
    [{ email: 'a@example.com', role: 'OWNER' }, 'Choose Admin or Staff.'],
    [{ email: `${'a'.repeat(250)}@example.com`, role: 'STAFF' }, 'Enter a valid email address.'],
    [null, 'Enter a valid email address.'],
  ])('rejects invalid input %j without calling the backend', async (input, message) => {
    expect(await inviteTeamMemberAction(input)).toEqual({ success: false, error: message });
    expect(mocks.createTeamInvitation).not.toHaveBeenCalled();
  });

  it('requires a verified session', async () => {
    mocks.getVerifiedUserId.mockResolvedValue(null);

    const result = await inviteTeamMemberAction({ email: 'a@example.com', role: 'ADMIN' });

    expect(result).toEqual({
      success: false,
      error: 'Your session has expired. Please sign in again.',
    });
    expect(mocks.createTeamInvitation).not.toHaveBeenCalled();
  });

  it.each([
    [401, 'x', 'Your session has expired. Please sign in again.'],
    [403, 'x', 'Only an organisation owner or admin can manage the team.'],
    [404, 'x', 'We could not find this organisation.'],
    [409, 'Already a member of this organization', 'Already a member of this organization'],
    [409, 'Too many pending invitations', 'Too many pending invitations'],
    [
      409,
      'The Free plan allows 1 team member. Upgrade your plan to add more.',
      'The Free plan allows 1 team member. Upgrade your plan to add more.',
    ],
    [409, 'SECRET internal detail', 'We could not send the invitation. Please try again.'],
    [422, 'x', 'Enter a valid email address.'],
    [503, 'x', 'Invitations are not available right now. Please try again later.'],
    [500, 'x', 'We could not send the invitation. Please try again.'],
    [
      undefined,
      NO_TEAM_ORGANIZATION_MESSAGE,
      'Create a store first. Your team belongs to your store’s organisation.',
    ],
  ])('maps status %s to a curated message', async (status, error, message) => {
    mocks.createTeamInvitation.mockResolvedValue({ success: false, error, status });

    const result = await inviteTeamMemberAction({ email: 'a@example.com', role: 'STAFF' });

    expect(result).toEqual({ success: false, error: message });
  });

  it('answers a generic message when the call throws', async () => {
    mocks.createTeamInvitation.mockRejectedValue(new TypeError('boom'));

    const result = await inviteTeamMemberAction({ email: 'a@example.com', role: 'STAFF' });

    expect(result).toEqual({
      success: false,
      error: 'We could not send the invitation. Please try again.',
    });
  });

  it('never logs the link', async () => {
    await inviteTeamMemberAction({ email: 'a@example.com', role: 'STAFF' });
    mocks.createTeamInvitation.mockResolvedValue({ success: false, error: 'x', status: 500 });
    await inviteTeamMemberAction({ email: 'a@example.com', role: 'STAFF' });

    expect(logged()).not.toContain(TOKEN);
  });
});

describe('acceptInvitationAction', () => {
  it('accepts and refreshes the dashboard', async () => {
    expect(await acceptInvitationAction(TOKEN)).toEqual({ success: true, data: { role: 'ADMIN' } });
    expect(mocks.acceptTeamInvitation).toHaveBeenCalledWith(TOKEN);
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/dashboard', 'layout');
  });

  it.each(['short', 'has spaces in it 1234567', 42, null, 'a'.repeat(129)])(
    'rejects malformed token %j without calling the backend',
    async (token) => {
      expect(await acceptInvitationAction(token)).toEqual({
        success: false,
        error: 'This invitation link is not valid.',
        kind: 'other',
      });
      expect(mocks.acceptTeamInvitation).not.toHaveBeenCalled();
    }
  );

  it('requires a verified session', async () => {
    mocks.getVerifiedUserId.mockResolvedValue(null);

    expect(await acceptInvitationAction(TOKEN)).toEqual({
      success: false,
      error: 'Your session has expired. Please sign in again.',
      kind: 'other',
    });
  });

  it.each([
    [401, 'x', 'Your session has expired. Please sign in again.', 'other'],
    [
      403,
      'x',
      'This invitation was sent to a different email address. Sign in with that address to accept it.',
      'wrong_account',
    ],
    [
      409,
      'Already a member of this organization',
      'Already a member of this organization',
      'other',
    ],
    [
      409,
      'The Pro plan allows 5 team members. Upgrade your plan to add more.',
      'The Pro plan allows 5 team members. Upgrade your plan to add more.',
      'other',
    ],
    [
      409,
      'SECRET internal detail',
      'We could not accept the invitation. Please try again.',
      'other',
    ],
    [410, 'x', 'This invitation is invalid, has already been used or has expired.', 'other'],
    [422, 'x', 'This invitation link is not valid.', 'other'],
    [500, 'x', 'We could not accept the invitation. Please try again.', 'other'],
  ])('maps status %s (%s) to a curated message', async (status, error, message, kind) => {
    mocks.acceptTeamInvitation.mockResolvedValue({ success: false, error, status });

    expect(await acceptInvitationAction(TOKEN)).toEqual({ success: false, error: message, kind });
  });

  it('answers a generic message when the call throws, without logging the token', async () => {
    mocks.acceptTeamInvitation.mockRejectedValue(new Error(TOKEN));

    expect(await acceptInvitationAction(TOKEN)).toEqual({
      success: false,
      error: 'We could not accept the invitation. Please try again.',
      kind: 'other',
    });
    expect(logged()).not.toContain(TOKEN);
  });
});
