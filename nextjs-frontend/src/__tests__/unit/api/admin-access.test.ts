// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ fetchProfile: vi.fn() }));
vi.mock('@/lib/api/account', () => ({ fetchProfile: mocks.fetchProfile }));

import { resolveAdminAccess } from '@/lib/api/admin-access';

const ok = (overrides: Record<string, unknown> = {}) => ({
  success: true,
  data: {
    email: 'a@example.com',
    display_name: 'Ada',
    avatar_url: 'https://img/a.png',
    is_admin: true,
    admin_role: 'super_admin',
    ...overrides,
  },
});

describe('resolveAdminAccess', () => {
  beforeEach(() => vi.clearAllMocks());

  it('grants access to an admin with a role and maps the viewer', async () => {
    mocks.fetchProfile.mockResolvedValue(ok());
    await expect(resolveAdminAccess()).resolves.toEqual({
      status: 'admin',
      viewer: {
        email: 'a@example.com',
        displayName: 'Ada',
        avatarUrl: 'https://img/a.png',
        adminRole: 'super_admin',
      },
    });
  });

  it('maps absent display name and avatar to null', async () => {
    mocks.fetchProfile.mockResolvedValue(ok({ display_name: undefined, avatar_url: undefined }));
    const access = await resolveAdminAccess();
    expect(access).toMatchObject({ viewer: { displayName: null, avatarUrl: null } });
  });

  it.each([false, undefined, null, 'true', 1])('denies is_admin=%s', async (value) => {
    mocks.fetchProfile.mockResolvedValue(ok({ is_admin: value }));
    await expect(resolveAdminAccess()).resolves.toEqual({ status: 'not-admin' });
  });

  it.each([null, undefined, ''])('denies an admin whose role is %j', async (role) => {
    mocks.fetchProfile.mockResolvedValue(ok({ admin_role: role }));
    await expect(resolveAdminAccess()).resolves.toEqual({ status: 'not-admin' });
  });

  it.each([null, undefined])('denies a success response with data=%s', async (data) => {
    mocks.fetchProfile.mockResolvedValue({ success: true, data });
    await expect(resolveAdminAccess()).resolves.toEqual({ status: 'not-admin' });
  });

  it.each([
    [401, 'Invalid authentication'],
    [404, 'Not found'],
  ])('reports a rejected session (%s)', async (status, error) => {
    mocks.fetchProfile.mockResolvedValue({ success: false, status, error });
    await expect(resolveAdminAccess()).resolves.toEqual({ status: 'session-rejected' });
  });

  it('reports other failures as errors with the status', async () => {
    mocks.fetchProfile.mockResolvedValue({ success: false, status: 500, error: 'Request failed' });
    await expect(resolveAdminAccess()).resolves.toEqual({
      status: 'error',
      message: 'Profile request failed (500)',
    });
  });

  it('reports an unreachable backend as an error', async () => {
    mocks.fetchProfile.mockResolvedValue({ success: false, error: 'Backend unavailable' });
    await expect(resolveAdminAccess()).resolves.toEqual({
      status: 'error',
      message: 'Profile request failed (unreachable)',
    });
  });
});
