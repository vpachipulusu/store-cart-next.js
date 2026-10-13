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
vi.mock('@/lib/db/client', () => ({
  db: {
    user: { findUnique: mocks.userFindUnique },
    notification: { count: vi.fn().mockResolvedValue(0), findMany: vi.fn().mockResolvedValue([]) },
  },
}));
vi.mock('@/lib/logger', () => ({ logger: { error: mocks.loggerError } }));
vi.mock('@/components/providers/session-provider', () => ({ SessionProvider: () => null }));
vi.mock('@/components/dashboard/dashboard-header', () => ({ DashboardHeader: () => null }));

import DashboardLayout from '@/app/dashboard/layout';

describe('DashboardLayout session check', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.cookieGet.mockImplementation((name: string) =>
      name === 'session' ? { value: 'cookie-value' } : undefined
    );
    mocks.verifySessionCookie.mockResolvedValue({
      uid: 'uid-1',
      email: 'a@b.test',
      email_verified: true,
    });
    mocks.userFindUnique.mockResolvedValue({ id: 'u1', displayName: null, avatarUrl: null });
  });

  it('propagates the /login redirect when there is no session cookie', async () => {
    mocks.cookieGet.mockReturnValue(undefined);

    const error = await rejection(DashboardLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/login');
    expect(mocks.loggerError).not.toHaveBeenCalled();
  });

  describe('KAN-123: email-verified claim', () => {
    const unverified = { uid: 'uid-1', email: 'a@b.test', email_verified: false };
    const withCookies = (jar: Record<string, string>) =>
      mocks.cookieGet.mockImplementation((name: string) =>
        name in jar ? { value: jar[name] } : undefined
      );

    it('sends an unverified user to /verify-email', async () => {
      mocks.verifySessionCookie.mockResolvedValue(unverified);

      const error = await rejection(DashboardLayout({ children: null }));

      expect(redirectTarget(error)).toBe('/verify-email');
      expect(mocks.userFindUnique).not.toHaveBeenCalled();
    });

    it('does not trust a forged email-verified=true cookie', async () => {
      withCookies({ session: 'cookie-value', 'email-verified': 'true' });
      mocks.verifySessionCookie.mockResolvedValue(unverified);

      const error = await rejection(DashboardLayout({ children: null }));

      expect(redirectTarget(error)).toBe('/verify-email');
    });

    it('does not trust a missing email-verified cookie either way', async () => {
      withCookies({ session: 'cookie-value' });
      mocks.verifySessionCookie.mockResolvedValue(unverified);

      expect(redirectTarget(await rejection(DashboardLayout({ children: null })))).toBe(
        '/verify-email'
      );
    });

    it('lets a verified user through even when the cookie is stale (false)', async () => {
      withCookies({ session: 'cookie-value', 'email-verified': 'false' });

      await expect(DashboardLayout({ children: null })).resolves.toBeDefined();
      expect(navigationMock.redirect).not.toHaveBeenCalled();
    });

    it('checks revocation, and a revoked session clears the session', async () => {
      const revoked = Object.assign(new Error('revoked'), { code: 'auth/session-cookie-revoked' });
      mocks.verifySessionCookie.mockRejectedValue(revoked);

      const error = await rejection(DashboardLayout({ children: null }));

      expect(mocks.verifySessionCookie).toHaveBeenCalledWith('cookie-value', true);
      expect(redirectTarget(error)).toBe('/api/auth/clear-session');
    });
  });

  it('clears the session when the session cookie has expired', async () => {
    mocks.verifySessionCookie.mockRejectedValue(SESSION_EXPIRED);

    const error = await rejection(DashboardLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/api/auth/clear-session');
    expect(mocks.loggerError).not.toHaveBeenCalled();
  });

  it('logs and rethrows a database error without clearing the session', async () => {
    mocks.userFindUnique.mockRejectedValue(DB_DOWN);

    const error = await rejection(DashboardLayout({ children: null }));

    expect(error).toBe(DB_DOWN);
    expect(navigationMock.redirect).not.toHaveBeenCalled();
    expect(mocks.loggerError).toHaveBeenCalledTimes(1);
    const [, meta] = mocks.loggerError.mock.calls[0];
    expect(meta).toMatchObject({
      route: '/dashboard',
      errorName: 'Error',
      message: 'connection refused',
      userId: 'uid-1',
    });
    expect(JSON.stringify(mocks.loggerError.mock.calls)).not.toContain('cookie-value');
  });
});
