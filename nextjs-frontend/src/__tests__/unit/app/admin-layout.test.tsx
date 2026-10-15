// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  DB_DOWN,
  SESSION_EXPIRED,
  navigationMock,
  redirectTarget,
  rejection,
} from './route-test-helpers';

const mocks = vi.hoisted(() => ({
  cookieGet: vi.fn(),
  verifySessionCookie: vi.fn(),
  userFindUnique: vi.fn(),
  loggerError: vi.fn(),
}));

vi.mock('next/navigation', () => navigationMock);
vi.mock('next/headers', () => ({ cookies: async () => ({ get: mocks.cookieGet }) }));
vi.mock('@/lib/firebase/admin', () => ({
  getAdminAuth: () => ({ verifySessionCookie: mocks.verifySessionCookie }),
}));
vi.mock('@/lib/db/client', () => ({ db: { user: { findUnique: mocks.userFindUnique } } }));
vi.mock('@/lib/logger', () => ({ logger: { error: mocks.loggerError } }));
vi.mock('@/components/admin/admin-header', () => ({ AdminHeader: () => null }));

import AdminLayout from '@/app/(admin)/admin/layout';

describe('AdminLayout access check', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.cookieGet.mockReturnValue({ value: 'cookie-value' });
    mocks.verifySessionCookie.mockResolvedValue({ uid: 'uid-1', email_verified: true });
  });

  it('sends a logged-in non-admin straight to /dashboard, never /login', async () => {
    mocks.userFindUnique.mockResolvedValue({ id: 'u1', adminUser: null });

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/dashboard');
    expect(navigationMock.redirect).toHaveBeenCalledTimes(1);
    expect(navigationMock.redirect).not.toHaveBeenCalledWith('/login');
  });

  it('sends an unverified admin to /verify-email without touching the database (KAN-123)', async () => {
    mocks.verifySessionCookie.mockResolvedValue({ uid: 'uid-1', email_verified: false });

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/verify-email');
    expect(mocks.userFindUnique).not.toHaveBeenCalled();
  });

  it('redirects to /login when the session cookie has expired', async () => {
    mocks.verifySessionCookie.mockRejectedValue(SESSION_EXPIRED);

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/login');
    expect(mocks.loggerError).not.toHaveBeenCalled();
  });

  it('logs and rethrows a database error instead of redirecting to /login', async () => {
    mocks.userFindUnique.mockRejectedValue(DB_DOWN);

    const error = await rejection(AdminLayout({ children: null }));

    expect(error).toBe(DB_DOWN);
    expect(navigationMock.redirect).not.toHaveBeenCalled();
    expect(mocks.loggerError).toHaveBeenCalledTimes(1);
    const [, meta] = mocks.loggerError.mock.calls[0];
    expect(meta).toMatchObject({
      route: '/admin',
      errorName: 'Error',
      message: 'connection refused',
      userId: 'uid-1',
    });
    expect(JSON.stringify(mocks.loggerError.mock.calls)).not.toContain('cookie-value');
  });
});
