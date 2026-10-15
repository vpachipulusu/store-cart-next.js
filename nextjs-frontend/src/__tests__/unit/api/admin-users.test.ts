// @vitest-environment node
/**
 * KAN-184: the admin users wrappers call the /v1/admin/users routes with the session cookie and the
 * internal key, and map failures to curated messages that never carry backend text.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const cookieGet = vi.fn();
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: cookieGet })),
  headers: vi.fn(async () => ({ get: vi.fn() })),
}));

import {
  ADMIN_FORBIDDEN_MESSAGE,
  ADMIN_REQUEST_FAILED_MESSAGE,
  ADMIN_UNAVAILABLE_MESSAGE,
  ADMIN_USER_NOT_FOUND_MESSAGE,
  adminErrorMessage,
  banAdminUser,
  fetchAdminUser,
  fetchAdminUsers,
  grantAdminRole,
  patchAdminUser,
  removeAdminUser,
  revokeAdminRole,
  toAdminUserDetail,
  toAdminUserSummary,
  unbanAdminUser,
} from '@/lib/api/admin-users';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const SUMMARY = {
  id: 'user-1',
  email: 'a@b.test',
  email_verified: true,
  display_name: 'Ada',
  avatar_url: null,
  created_at: '2026-01-01T00:00:00Z',
  last_login_at: null,
  is_admin: true,
  admin_role: 'super_admin',
};

const DETAIL = {
  ...SUMMARY,
  bio: 'bio',
  location: 'London',
  website: null,
  phone_number: null,
  two_factor_enabled: true,
  admin_permissions: ['users.read'],
};

describe('admin users wrappers', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

  beforeEach(() => {
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
    vi.stubEnv('BACKEND_INTERNAL_KEY', 'server-key');
    cookieGet.mockReturnValue({ name: 'session', value: 'firebase-session-cookie' });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    cookieGet.mockReset();
  });

  it('fetchAdminUsers lists with paging, a trimmed search, and the session headers', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        success: true,
        data: { users: [SUMMARY], total_count: 1, limit: 50, offset: 0 },
      })
    );

    const result = await fetchAdminUsers({ search: '  ada  ', offset: 50 });

    expect(result).toEqual({
      success: true,
      data: { users: [SUMMARY], total_count: 1, limit: 50, offset: 0 },
    });
    const request = fetchMock.mock.calls[0][0];
    const url = new URL(request.url);
    expect(url.pathname).toBe('/v1/admin/users');
    expect(url.searchParams.get('search')).toBe('ada');
    expect(url.searchParams.get('limit')).toBe('50');
    expect(url.searchParams.get('offset')).toBe('50');
    expect(request.headers.get('X-Session-Token')).toBe('firebase-session-cookie');
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
  });

  it('fetchAdminUsers omits an empty search', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: true, data: { users: [], total_count: 0, limit: 50, offset: 0 } })
    );

    await fetchAdminUsers({ search: '   ' });

    expect(new URL(fetchMock.mock.calls[0][0].url).searchParams.has('search')).toBe(false);
  });

  it('fetchAdminUser reads one user by id', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ success: true, data: DETAIL }));

    const result = await fetchAdminUser('user-1');

    expect(result).toEqual({ success: true, data: DETAIL });
    expect(new URL(fetchMock.mock.calls[0][0].url).pathname).toBe('/v1/admin/users/user-1');
  });

  it.each([
    ['patchAdminUser', () => patchAdminUser('u1', { bio: 'x' }), 'PATCH', '/v1/admin/users/u1'],
    ['removeAdminUser', () => removeAdminUser('u1'), 'DELETE', '/v1/admin/users/u1'],
    [
      'grantAdminRole',
      () => grantAdminRole('u1', { role: 'admin', permissions: [] }),
      'PUT',
      '/v1/admin/users/u1/admin',
    ],
    ['revokeAdminRole', () => revokeAdminRole('u1'), 'DELETE', '/v1/admin/users/u1/admin'],
    ['banAdminUser', () => banAdminUser('u1', 'spam'), 'POST', '/v1/admin/users/u1/ban'],
    ['unbanAdminUser', () => unbanAdminUser('u1'), 'POST', '/v1/admin/users/u1/unban'],
  ])('%s calls %s %s', async (_name, call, method, path) => {
    fetchMock.mockResolvedValue(jsonResponse({ success: true, data: DETAIL }));

    await call();

    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe(method);
    expect(new URL(request.url).pathname).toBe(path);
  });

  it('banAdminUser sends the reason in the body', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ success: true }));

    await banAdminUser('u1', 'spam');

    expect(await fetchMock.mock.calls[0][0].json()).toEqual({ reason: 'spam' });
  });

  it('carries the backend status on failure', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ success: false, error: 'Forbidden' }, 403));

    const result = await fetchAdminUser('u1');

    expect(result).toMatchObject({ success: false, status: 403 });
  });
});

describe('adminErrorMessage', () => {
  it.each([
    [401, ADMIN_FORBIDDEN_MESSAGE],
    [403, ADMIN_FORBIDDEN_MESSAGE],
    [404, ADMIN_USER_NOT_FOUND_MESSAGE],
    [409, ADMIN_REQUEST_FAILED_MESSAGE],
    [500, ADMIN_REQUEST_FAILED_MESSAGE],
    [undefined, ADMIN_UNAVAILABLE_MESSAGE],
  ])('status %s is answered with a fixed message', (status, message) => {
    expect(
      adminErrorMessage({ success: false, error: 'SECRET postgres://user:pw@host/db', status })
    ).toBe(message);
  });
});

describe('admin user mappers', () => {
  it('maps the summary to camelCase and exposes no extra fields', () => {
    expect(toAdminUserSummary(SUMMARY)).toEqual({
      id: 'user-1',
      email: 'a@b.test',
      emailVerified: true,
      displayName: 'Ada',
      avatarUrl: null,
      createdAt: '2026-01-01T00:00:00Z',
      lastLoginAt: null,
      isAdmin: true,
      adminRole: 'super_admin',
    });
  });

  it('maps the detail with profile, 2FA and permissions', () => {
    expect(toAdminUserDetail(DETAIL)).toMatchObject({
      bio: 'bio',
      location: 'London',
      twoFactorEnabled: true,
      adminPermissions: ['users.read'],
    });
  });
});
