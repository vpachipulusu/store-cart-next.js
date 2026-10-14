// @vitest-environment node
/**
 * KAN-129: auth server actions must never return raw Firebase/Prisma/library error text to the client.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const SECRET = 'SECRET-sk_live_abc123 postgres://user:pw@host/db';
const THROWING_EMAIL = 'boom@example.com';

const mocks = vi.hoisted(() => ({
  verifyIdToken: vi.fn(),
  verifySessionCookie: vi.fn(),
  revokeRefreshTokens: vi.fn(),
  createSessionCookie: vi.fn(),
  createBackendSession: vi.fn(),
  revokeBackendSession: vi.fn(),
  fetchProfile: vi.fn(),
  fetchSettings: vi.fn(),
  applyActionCode: vi.fn(),
  cookieGet: vi.fn(),
  cookieSet: vi.fn(),
  cookieDelete: vi.fn(),
  cookiesFn: vi.fn(),
  logError: vi.fn(),
}));

vi.mock('next/headers', () => ({
  headers: async () => new Headers({ 'user-agent': 'vitest' }),
  cookies: () => mocks.cookiesFn(),
}));
vi.mock('@/lib/firebase/admin', () => ({
  getAdminAuth: () => ({
    verifyIdToken: mocks.verifyIdToken,
    verifySessionCookie: mocks.verifySessionCookie,
    revokeRefreshTokens: mocks.revokeRefreshTokens,
    createSessionCookie: mocks.createSessionCookie,
  }),
}));
vi.mock('@/lib/firebase/client', () => ({ auth: {} }));
vi.mock('firebase/auth', () => ({ applyActionCode: mocks.applyActionCode }));
vi.mock('@/lib/api/account', () => ({
  createBackendSession: mocks.createBackendSession,
  revokeBackendSession: mocks.revokeBackendSession,
  fetchProfile: mocks.fetchProfile,
  fetchSettings: mocks.fetchSettings,
  toSettings: (settings: unknown) => settings,
}));
vi.mock('@/lib/auth/verified-session', () => ({
  isEmailNotVerifiedError: () => false,
  verifyVerifiedSessionCookie: (...args: unknown[]) => mocks.verifySessionCookie(...args),
}));
// The real schemas never throw, so a schema that does stands in for an unexpected internal failure.
vi.mock('@/lib/utils/validation', async () => {
  const { z } = await import('zod');
  return {
    emailSchema: z.string().transform((value) => {
      if (value === 'boom@example.com')
        throw new Error('SECRET-sk_live_abc123 postgres://user:pw@host/db');
      return value;
    }),
    passwordSchema: z.string(),
  };
});
vi.mock('@/lib/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: mocks.logError },
}));

import {
  getCurrentSessionAction,
  loginAction,
  logoutAction,
  refreshSessionAction,
  signUpAction,
  verifyEmailAction,
  verifyTokenAction,
} from '@/app/actions/auth-actions';

function expectNoLeak(result: { success: boolean; error?: string }, generic: string) {
  expect(result.success).toBe(false);
  expect(result.error).toBe(generic);
  expect(JSON.stringify(result)).not.toContain('SECRET');
}

describe('KAN-129: auth actions return generic errors', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.cookiesFn.mockResolvedValue({
      get: mocks.cookieGet,
      set: mocks.cookieSet,
      delete: mocks.cookieDelete,
    });
    mocks.cookieGet.mockReturnValue({ value: 'session-cookie' });
    mocks.revokeBackendSession.mockResolvedValue({ success: true, data: {} });
  });

  it('loginAction hides an unexpected failure and logs the detail', async () => {
    expectNoLeak(await loginAction(THROWING_EMAIL, 'pw'), 'Login failed');
    expect(mocks.logError).toHaveBeenCalled();
  });

  it('signUpAction hides an unexpected failure and logs the detail', async () => {
    expectNoLeak(await signUpAction(THROWING_EMAIL, 'Password123!'), 'Signup failed');
    expect(mocks.logError).toHaveBeenCalled();
  });

  it('logoutAction hides a cookie-store failure and logs the detail', async () => {
    mocks.cookiesFn.mockRejectedValue(new Error(SECRET));

    expectNoLeak(await logoutAction(), 'Logout failed');
    expect(mocks.logError).toHaveBeenCalled();
  });

  it('verifyEmailAction hides the Firebase error text and logs the detail', async () => {
    mocks.applyActionCode.mockRejectedValue(new Error(SECRET));

    expectNoLeak(await verifyEmailAction('oob'), 'Email verification failed');
    expect(mocks.logError).toHaveBeenCalled();
  });

  it('verifyTokenAction hides a Firebase token verification failure', async () => {
    mocks.verifyIdToken.mockRejectedValue(new Error(SECRET));

    expectNoLeak(await verifyTokenAction('tok'), 'Token verification failed');
  });

  it('verifyTokenAction hides a backend failure after the token verified', async () => {
    mocks.verifyIdToken.mockResolvedValue({ uid: 'u', email: 'a@b.co', email_verified: true });
    mocks.createBackendSession.mockResolvedValue({ success: false, error: SECRET, status: 500 });

    expectNoLeak(await verifyTokenAction('tok'), 'Token verification failed');
  });

  it('verifyTokenAction hides an unexpected exception from the backend wrapper', async () => {
    mocks.verifyIdToken.mockResolvedValue({ uid: 'u', email: 'a@b.co', email_verified: true });
    mocks.createBackendSession.mockRejectedValue(new Error(SECRET));

    expectNoLeak(await verifyTokenAction('tok'), 'Token verification failed');
  });

  it('refreshSessionAction hides a Firebase session cookie failure', async () => {
    mocks.verifyIdToken.mockResolvedValue({ uid: 'u', email: 'a@b.co', email_verified: true });
    mocks.verifySessionCookie.mockResolvedValue({ uid: 'u' });
    mocks.createSessionCookie.mockRejectedValue(new Error(SECRET));

    expectNoLeak(await refreshSessionAction('tok'), 'Token verification failed');
  });

  it('logoutAction still clears the cookie and hides a backend revocation failure', async () => {
    mocks.revokeBackendSession.mockResolvedValue({ success: false, error: SECRET, status: 500 });

    const result = await logoutAction();

    expect(result.success).toBe(true);
    expect(JSON.stringify(result)).not.toContain('SECRET');
    expect(mocks.cookieDelete).toHaveBeenCalledWith('session');
  });

  it('getCurrentSessionAction hides a backend profile failure', async () => {
    mocks.verifySessionCookie.mockResolvedValue({ uid: 'u' });
    mocks.fetchProfile.mockResolvedValue({ success: false, error: SECRET, status: 500 });
    mocks.fetchSettings.mockResolvedValue({ success: true, data: {} });

    expectNoLeak(await getCurrentSessionAction(), 'Session retrieval failed');
    // A backend outage must not sign the user out.
    expect(mocks.cookieDelete).not.toHaveBeenCalled();
  });

  it('getCurrentSessionAction clears the session when the backend rejects it', async () => {
    mocks.verifySessionCookie.mockResolvedValue({ uid: 'u' });
    mocks.fetchProfile.mockResolvedValue({
      success: false,
      error: 'Invalid authentication',
      status: 401,
    });
    mocks.fetchSettings.mockResolvedValue({ success: true, data: {} });

    expectNoLeak(await getCurrentSessionAction(), 'Session retrieval failed');
    expect(mocks.cookieDelete).toHaveBeenCalledWith('session');
  });

  it('logoutAction revokes through Firebase when the backend call fails with a server error', async () => {
    mocks.revokeBackendSession.mockResolvedValue({ success: false, error: 'x', status: 503 });
    mocks.verifySessionCookie.mockResolvedValue({ uid: 'u1' });

    await logoutAction();

    expect(mocks.revokeRefreshTokens).toHaveBeenCalledWith('u1');
  });

  it('logoutAction does not fall back when the backend already rejected the session', async () => {
    mocks.revokeBackendSession.mockResolvedValue({ success: false, error: 'x', status: 401 });

    await logoutAction();

    expect(mocks.revokeRefreshTokens).not.toHaveBeenCalled();
  });

  it('getCurrentSessionAction hides a verification or database failure', async () => {
    mocks.verifySessionCookie.mockRejectedValue(new Error(SECRET));

    expectNoLeak(await getCurrentSessionAction(), 'Session retrieval failed');
  });
});
