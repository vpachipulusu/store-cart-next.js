// @vitest-environment node
/**
 * KAN-50: the admin layout decides access through the API (profile + admin users API), not Prisma, and denies
 * by default. KAN-123 / KAN-141 behaviour is unchanged: unverified -> /verify-email, expired -> /login, a
 * logged-in non-admin goes straight to /dashboard.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { SESSION_EXPIRED, navigationMock, redirectTarget, rejection } from './route-test-helpers';

const mocks = vi.hoisted(() => ({
  cookieGet: vi.fn(),
  verifySessionCookie: vi.fn(),
  fetchAdminAccess: vi.fn(),
  dbFindUnique: vi.fn(),
  loggerError: vi.fn(),
  adminHeader: vi.fn(),
}));

vi.mock('next/navigation', () => navigationMock);
vi.mock('next/headers', () => ({ cookies: async () => ({ get: mocks.cookieGet }) }));
vi.mock('@/lib/firebase/admin', () => ({
  getAdminAuth: () => ({ verifySessionCookie: mocks.verifySessionCookie }),
}));
// verified-session.ts (not part of this ticket) still imports the client for its own lookups.
vi.mock('@/lib/db/client', () => ({ db: { user: { findUnique: mocks.dbFindUnique } } }));
vi.mock('@/lib/api/admin-access', () => ({ fetchAdminAccess: mocks.fetchAdminAccess }));
vi.mock('@/lib/logger', () => ({ logger: { error: mocks.loggerError } }));
vi.mock('@/components/admin/admin-header', () => ({
  AdminHeader: (props: unknown) => {
    mocks.adminHeader(props);
    return null;
  },
}));

import AdminLayout from '@/app/(admin)/admin/layout';

const ACCESS = {
  user: { email: 'ada@example.test', displayName: 'Ada', avatarUrl: null },
  adminRole: 'super_admin',
};

describe('AdminLayout access check', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.cookieGet.mockReturnValue({ value: 'cookie-value' });
    mocks.verifySessionCookie.mockResolvedValue({ uid: 'uid-1', email_verified: true });
    mocks.fetchAdminAccess.mockResolvedValue({ success: true, data: ACCESS });
  });

  it('does not import the database client itself', () => {
    const source = readFileSync(join(process.cwd(), 'src/app/(admin)/admin/layout.tsx'), 'utf8');

    expect(source).not.toContain('@/lib/db/client');
  });

  it('renders the admin shell with the header data for an admin', async () => {
    const tree = await AdminLayout({ children: 'child-content' });
    const markup = renderToStaticMarkup(tree as React.ReactElement);

    expect(markup).toContain('child-content');
    expect(markup).toContain('Admin Portal');
    expect(mocks.adminHeader).toHaveBeenCalledWith({ user: ACCESS.user, adminRole: 'super_admin' });
    expect(mocks.dbFindUnique).not.toHaveBeenCalled();
  });

  it('redirects to /login when there is no session cookie', async () => {
    mocks.cookieGet.mockReturnValue(undefined);

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/login');
    expect(mocks.fetchAdminAccess).not.toHaveBeenCalled();
  });

  it('sends a logged-in non-admin straight to /dashboard, never /login', async () => {
    mocks.fetchAdminAccess.mockResolvedValue({ success: true, data: null });

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/dashboard');
    expect(navigationMock.redirect).toHaveBeenCalledTimes(1);
    expect(navigationMock.redirect).not.toHaveBeenCalledWith('/login');
  });

  it('sends an unverified admin to /verify-email without asking the API (KAN-123)', async () => {
    mocks.verifySessionCookie.mockResolvedValue({ uid: 'uid-1', email_verified: false });

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/verify-email');
    expect(mocks.fetchAdminAccess).not.toHaveBeenCalled();
  });

  it('redirects to /login when the session cookie has expired', async () => {
    mocks.verifySessionCookie.mockRejectedValue(SESSION_EXPIRED);

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/login');
    expect(mocks.loggerError).not.toHaveBeenCalled();
  });

  it.each([
    [{ success: false, error: 'Invalid authentication', status: 401 }],
    [{ success: false, error: 'Not found', status: 404 }],
  ])('clears the session when the backend rejects it (%o)', async (failure) => {
    mocks.fetchAdminAccess.mockResolvedValue(failure);

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/api/auth/clear-session');
  });

  it.each([
    [{ success: false, error: 'Request failed', status: 500 }, '500'],
    [{ success: false, error: 'Backend unavailable' }, 'unreachable'],
  ])('fails closed on an API outage instead of redirecting (%o)', async (failure, detail) => {
    mocks.fetchAdminAccess.mockResolvedValue(failure);

    const error = await rejection(AdminLayout({ children: null }));

    expect(String(error)).toContain(detail);
    expect(navigationMock.redirect).not.toHaveBeenCalled();
    expect(mocks.loggerError).toHaveBeenCalledTimes(1);
    const [, meta] = mocks.loggerError.mock.calls[0];
    expect(meta).toMatchObject({ route: '/admin', userId: 'uid-1' });
    expect(JSON.stringify(mocks.loggerError.mock.calls)).not.toContain('cookie-value');
  });

  it('logs and rethrows an unexpected error instead of redirecting to /login', async () => {
    const boom = new Error('boom');
    mocks.fetchAdminAccess.mockRejectedValue(boom);

    const error = await rejection(AdminLayout({ children: null }));

    expect(error).toBe(boom);
    expect(navigationMock.redirect).not.toHaveBeenCalled();
    expect(mocks.loggerError).toHaveBeenCalledTimes(1);
  });
});
