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
  fetchProfile: vi.fn(),
  loggerError: vi.fn(),
}));

vi.mock('next/navigation', () => navigationMock);
vi.mock('next/headers', () => ({ cookies: async () => ({ get: mocks.cookieGet }) }));
vi.mock('@/lib/firebase/admin', () => ({
  getAdminAuth: () => ({ verifySessionCookie: mocks.verifySessionCookie }),
}));
vi.mock('@/lib/api/account', () => ({ fetchProfile: mocks.fetchProfile }));
vi.mock('@/lib/logger', () => ({ logger: { error: mocks.loggerError } }));
vi.mock('@/components/providers/session-provider', () => ({ SessionProvider: () => null }));
vi.mock('@/components/dashboard/dashboard-header', () => ({ DashboardHeader: () => null }));

import DashboardLayout from '@/app/dashboard/layout';

/** Finds the props.user handed to DashboardHeader in the rendered element tree. */
function findHeaderUser(node: unknown): Record<string, unknown> | undefined {
  if (!node || typeof node !== 'object') return undefined;
  const element = node as { props?: { user?: Record<string, unknown>; children?: unknown } };
  if (element.props?.user && 'dbDisplayName' in element.props.user) return element.props.user;
  const children = element.props?.children;
  for (const child of Array.isArray(children) ? children : [children]) {
    const found = findHeaderUser(child);
    if (found) return found;
  }
  return undefined;
}

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
    mocks.fetchProfile.mockResolvedValue({
      success: true,
      data: { display_name: null, avatar_url: null },
    });
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
      expect(mocks.fetchProfile).not.toHaveBeenCalled();
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

  it('logs and rethrows a profile request error without clearing the session', async () => {
    mocks.fetchProfile.mockRejectedValue(DB_DOWN);

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

  describe('KAN-41: profile comes from the API', () => {
    it('passes the API display name and avatar to the header', async () => {
      mocks.fetchProfile.mockResolvedValue({
        success: true,
        data: { display_name: 'Ada', avatar_url: 'https://x.test/a.png' },
      });

      const tree = await DashboardLayout({ children: null });

      expect(findHeaderUser(tree)).toMatchObject({
        dbDisplayName: 'Ada',
        dbAvatarUrl: 'https://x.test/a.png',
      });
    });

    it.each([
      [401, 'Invalid authentication'],
      [404, 'Not found'],
    ])('clears the session when the backend answers %s (%s)', async (status, error) => {
      mocks.fetchProfile.mockResolvedValue({ success: false, error, status });

      const err = await rejection(DashboardLayout({ children: null }));

      expect(redirectTarget(err)).toBe('/api/auth/clear-session');
    });

    it('does not clear the session for a 401 caused by a misconfigured internal key', async () => {
      mocks.fetchProfile.mockResolvedValue({ success: false, error: 'Unauthorized', status: 401 });

      const err = await rejection(DashboardLayout({ children: null }));

      expect(navigationMock.redirect).not.toHaveBeenCalled();
      expect(String(err)).toContain('Profile request failed (401)');
      expect(mocks.loggerError).toHaveBeenCalledTimes(1);
    });

    it('rethrows when the backend is unreachable, keeping the session', async () => {
      mocks.fetchProfile.mockResolvedValue({ success: false, error: 'Backend unavailable' });

      const err = await rejection(DashboardLayout({ children: null }));

      expect(navigationMock.redirect).not.toHaveBeenCalled();
      expect(String(err)).toContain('unreachable');
    });
  });
});
