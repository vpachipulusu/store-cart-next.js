// @vitest-environment node
/**
 * KAN-184: the admin user actions run through the admin users API wrapper (KAN-47). They validate input
 * before any call, answer failures with curated messages, and never return backend error text.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const SECRET = 'SECRET-sk_live_abc123 postgres://user:pw@host/db';

const mocks = vi.hoisted(() => ({
  fetchAdminUsers: vi.fn(),
  fetchAdminUser: vi.fn(),
  patchAdminUser: vi.fn(),
  removeAdminUser: vi.fn(),
  grantAdminRole: vi.fn(),
  revokeAdminRole: vi.fn(),
  banAdminUser: vi.fn(),
  unbanAdminUser: vi.fn(),
  logError: vi.fn(),
}));

vi.mock('@/lib/api/admin-users', async () => {
  const actual =
    await vi.importActual<typeof import('@/lib/api/admin-users')>('@/lib/api/admin-users');
  return { ...actual, ...mocks };
});
vi.mock('@/lib/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: mocks.logError },
}));

import {
  banUserAction,
  deleteUserAction,
  getAllUsersAction,
  getUserByIdAction,
  grantAdminRoleAction,
  revokeAdminRoleAction,
  unbanUserAction,
  updateUserAction,
} from '@/app/actions/admin/user-actions';

const SUMMARY = {
  id: 'user-1',
  email: 'a@b.test',
  email_verified: true,
  display_name: 'Ada',
  avatar_url: null,
  created_at: '2026-01-01T00:00:00Z',
  last_login_at: null,
  is_admin: false,
  admin_role: null,
};
const DETAIL = {
  ...SUMMARY,
  bio: null,
  location: null,
  website: null,
  phone_number: null,
  two_factor_enabled: false,
  admin_permissions: [],
};

const ok = <T>(data: T) => ({ success: true as const, data });
const fail = (status?: number) => ({ success: false as const, error: SECRET, status });

describe('admin user actions (API-backed)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('getAllUsersAction maps users and computes pagination from the offset', async () => {
    mocks.fetchAdminUsers.mockResolvedValue(
      ok({ users: [SUMMARY], total_count: 45, limit: 20, offset: 20 })
    );

    const result = await getAllUsersAction(2, 20, { search: 'ada' });

    expect(mocks.fetchAdminUsers).toHaveBeenCalledWith({ search: 'ada', limit: 20, offset: 20 });
    expect(result.data.users[0]).toMatchObject({ id: 'user-1', emailVerified: true });
    expect(result.data.pagination).toEqual({ page: 2, limit: 20, totalCount: 45, totalPages: 3 });
  });

  it('getAllUsersAction clamps the page size', async () => {
    mocks.fetchAdminUsers.mockResolvedValue(
      ok({ users: [], total_count: 0, limit: 100, offset: 0 })
    );

    await getAllUsersAction(1, 10_000);

    expect(mocks.fetchAdminUsers.mock.calls[0][0].limit).toBe(100);
  });

  it('getUserByIdAction returns the mapped detail', async () => {
    mocks.fetchAdminUser.mockResolvedValue(ok(DETAIL));

    const result = await getUserByIdAction('user-1');

    expect(result.success).toBe(true);
    expect(result.data.user).toMatchObject({ id: 'user-1', twoFactorEnabled: false });
  });

  it('updateUserAction sends only the provided profile fields in API naming', async () => {
    mocks.patchAdminUser.mockResolvedValue(ok(DETAIL));

    const result = await updateUserAction('user-1', { displayName: 'Ada L', bio: null });

    expect(mocks.patchAdminUser).toHaveBeenCalledWith('user-1', {
      display_name: 'Ada L',
      bio: null,
    });
    expect(result.success).toBe(true);
  });

  it('grantAdminRoleAction rejects an unknown role before calling the API', async () => {
    const result = await grantAdminRoleAction('user-1', {
      role: 'owner' as never,
      permissions: [],
    });

    expect(result.success).toBe(false);
    expect(mocks.grantAdminRole).not.toHaveBeenCalled();
  });

  it('grantAdminRoleAction returns the role and permissions', async () => {
    mocks.grantAdminRole.mockResolvedValue(
      ok({ user_id: 'user-1', role: 'admin', permissions: ['users.read'] })
    );

    const result = await grantAdminRoleAction('user-1', {
      role: 'admin',
      permissions: ['users.read'],
    });

    expect(result.data).toEqual({ adminUser: { role: 'admin', permissions: ['users.read'] } });
  });

  it.each([
    ['deleteUserAction', () => deleteUserAction('u1'), mocks.removeAdminUser],
    ['revokeAdminRoleAction', () => revokeAdminRoleAction('u1'), mocks.revokeAdminRole],
    ['banUserAction', () => banUserAction('u1', 'spam'), mocks.banAdminUser],
    ['unbanUserAction', () => unbanUserAction('u1'), mocks.unbanAdminUser],
  ])('%s reports success from the API', async (_name, call, api) => {
    api.mockResolvedValue(ok({}));

    const result = await call();

    expect(result.success).toBe(true);
    expect(api).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['getUserByIdAction', () => getUserByIdAction('u1'), mocks.fetchAdminUser],
    ['updateUserAction', () => updateUserAction('u1', { bio: 'x' }), mocks.patchAdminUser],
    ['deleteUserAction', () => deleteUserAction('u1'), mocks.removeAdminUser],
    ['banUserAction', () => banUserAction('u1'), mocks.banAdminUser],
    ['unbanUserAction', () => unbanUserAction('u1'), mocks.unbanAdminUser],
    ['revokeAdminRoleAction', () => revokeAdminRoleAction('u1'), mocks.revokeAdminRole],
  ])('%s answers a 403 with the permission message and no backend text', async (_n, call, api) => {
    api.mockResolvedValue(fail(403));

    const result = await call();

    expect(result).toEqual({ success: false, error: 'You do not have permission to do that' });
    expect(JSON.stringify(result)).not.toContain('SECRET');
  });

  it('answers a 404 with a not-found message and does not log it', async () => {
    mocks.fetchAdminUser.mockResolvedValue(fail(404));

    const result = await getUserByIdAction('u1');

    expect(result.error).toBe('User not found');
    expect(mocks.logError).not.toHaveBeenCalled();
  });

  it('logs a server failure with its status only and answers generically', async () => {
    mocks.fetchAdminUsers.mockResolvedValue(fail(500));

    const result = await getAllUsersAction();

    expect(result.error).toBe('Something went wrong. Please try again.');
    expect(mocks.logError).toHaveBeenCalledWith(expect.any(String), { status: 500 });
    expect(JSON.stringify(mocks.logError.mock.calls)).not.toContain('SECRET');
  });

  it('answers an unreachable backend with the unavailable message', async () => {
    mocks.fetchAdminUser.mockResolvedValue(fail(undefined));

    const result = await getUserByIdAction('u1');

    expect(result.error).toBe('The admin service is unavailable. Please try again later.');
  });

  it.each(['../etc', 'a/b', '', 'x'.repeat(200)])(
    'rejects the user id %j without calling the API',
    async (id) => {
      const results = await Promise.all([
        getUserByIdAction(id),
        updateUserAction(id, { bio: 'x' }),
        deleteUserAction(id),
        revokeAdminRoleAction(id),
        banUserAction(id),
        unbanUserAction(id),
      ]);

      for (const result of results) {
        expect(result).toEqual({ success: false, error: 'User not found' });
      }
      for (const api of [
        mocks.fetchAdminUser,
        mocks.patchAdminUser,
        mocks.removeAdminUser,
        mocks.revokeAdminRole,
        mocks.banAdminUser,
        mocks.unbanAdminUser,
      ]) {
        expect(api).not.toHaveBeenCalled();
      }
    }
  );
});
