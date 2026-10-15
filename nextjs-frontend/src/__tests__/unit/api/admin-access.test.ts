// @vitest-environment node
/**
 * KAN-50: the admin gate no longer reads Prisma. It asks the API who the caller is and whether that user is an
 * admin, and denies by default: only an explicit admin answer grants access.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ fetchProfile: vi.fn(), fetchAdminUser: vi.fn() }));

vi.mock('@/lib/api/account', () => ({ fetchProfile: mocks.fetchProfile }));
vi.mock('@/lib/api/admin-users', () => ({ fetchAdminUser: mocks.fetchAdminUser }));

import { fetchAdminAccess } from '@/lib/api/admin-access';

const PROFILE = {
  id: 'user-1',
  email: 'ada@example.test',
  display_name: 'Ada',
  avatar_url: 'https://example.test/a.png',
};
const ADMIN_DETAIL = { ...PROFILE, is_admin: true, admin_role: 'super_admin' };

describe('fetchAdminAccess', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.fetchProfile.mockResolvedValue({ success: true, data: PROFILE });
    mocks.fetchAdminUser.mockResolvedValue({ success: true, data: ADMIN_DETAIL });
  });

  it('grants access to an admin and returns the header data', async () => {
    const result = await fetchAdminAccess();

    expect(result).toEqual({
      success: true,
      data: {
        user: {
          email: 'ada@example.test',
          displayName: 'Ada',
          avatarUrl: 'https://example.test/a.png',
        },
        adminRole: 'super_admin',
      },
    });
    expect(mocks.fetchAdminUser).toHaveBeenCalledWith('user-1');
  });

  it('denies a user the admin API says is not an admin', async () => {
    mocks.fetchAdminUser.mockResolvedValue({
      success: true,
      data: { ...ADMIN_DETAIL, is_admin: false, admin_role: null },
    });

    expect(await fetchAdminAccess()).toEqual({ success: true, data: null });
  });

  it('denies an admin answer that carries no role', async () => {
    mocks.fetchAdminUser.mockResolvedValue({
      success: true,
      data: { ...ADMIN_DETAIL, admin_role: null },
    });

    expect(await fetchAdminAccess()).toEqual({ success: true, data: null });
  });

  it.each([401, 403, 404])('denies when the admin API answers %s', async (status) => {
    mocks.fetchAdminUser.mockResolvedValue({ success: false, error: 'x', status });

    expect(await fetchAdminAccess()).toEqual({ success: true, data: null });
  });

  it.each([
    [{ success: false, error: 'Request failed', status: 500 }],
    [{ success: false, error: 'Backend unavailable' }],
  ])('reports an outage of the admin API as a failure, never as access (%o)', async (failure) => {
    mocks.fetchAdminUser.mockResolvedValue(failure);

    const result = await fetchAdminAccess();

    expect(result.success).toBe(false);
  });

  it('passes a profile failure through without calling the admin API', async () => {
    const failure = { success: false, error: 'Invalid authentication', status: 401 };
    mocks.fetchProfile.mockResolvedValue(failure);

    expect(await fetchAdminAccess()).toEqual(failure);
    expect(mocks.fetchAdminUser).not.toHaveBeenCalled();
  });
});
