// @vitest-environment node
/**
 * Regression tests for KAN-122: auth server actions must not allow account takeover or plan escalation.
 * KAN-41: sign-in goes through the API; a session refresh records no login.
 */
import { existsSync } from 'node:fs';
import path from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SIGN_IN_SERVICE_UNAVAILABLE_ERROR } from '@/lib/auth/auth-error-messages';

const mocks = vi.hoisted(() => ({
  verifyBackendIdToken: vi.fn(),
  fetchSessionStatus: vi.fn(),
  createBackendSession: vi.fn(),
  refreshBackendSession: vi.fn(),
  cookieGet: vi.fn(),
  cookieSet: vi.fn(),
  cookieDelete: vi.fn(),
}));

vi.mock('next/headers', () => ({
  headers: async () => new Headers({ 'user-agent': 'vitest' }),
  cookies: async () => ({
    set: mocks.cookieSet,
    get: mocks.cookieGet,
    delete: mocks.cookieDelete,
  }),
}));
vi.mock('@/lib/firebase/client', () => ({ auth: {} }));
vi.mock('firebase/auth', () => ({ applyActionCode: vi.fn() }));
vi.mock('@/lib/api/account', () => ({
  createBackendSession: mocks.createBackendSession,
  refreshBackendSession: mocks.refreshBackendSession,
  verifyBackendIdToken: mocks.verifyBackendIdToken,
  fetchSessionStatus: mocks.fetchSessionStatus,
  revokeBackendSession: vi.fn(),
  fetchProfile: vi.fn(),
  fetchSettings: vi.fn(),
  toSettings: (settings: unknown) => settings,
}));
vi.mock('@/lib/logger', () => ({ logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() } }));

import * as authActions from '@/app/actions/auth-actions';

const REVOKED_SESSION = { success: false, error: 'Invalid authentication', status: 401 };
const idTokenOk = (emailVerified: boolean) => ({
  success: true,
  data: { uid: 'uid-1', email: 'new@example.com', email_verified: emailVerified },
});
const sessionOk = (uid: string) => ({
  success: true,
  data: { uid, email: 'new@example.com', email_verified: true },
});

describe('KAN-122: auth server actions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.verifyBackendIdToken.mockResolvedValue(idTokenOk(false));
    mocks.createBackendSession.mockResolvedValue({
      success: true,
      data: { session_cookie: 'backend-session-cookie', expires_in: 432000 },
    });
    mocks.refreshBackendSession.mockResolvedValue({
      success: true,
      data: { session_cookie: 'refreshed-session-cookie', expires_in: 432000 },
    });
    mocks.cookieGet.mockReturnValue(undefined);
  });

  it('no longer exports the unauthenticated password-reset action that leaked the reset link', () => {
    expect(authActions).not.toHaveProperty('requestPasswordResetAction');
  });

  it('no longer exports the unauthenticated user-sync action', () => {
    expect(authActions).not.toHaveProperty('syncUserAction');
  });

  it.each(['signup', 'login', 'logout'])(
    'no longer ships the unused, unauthenticated /api/auth/%s route',
    (route) => {
      const routeFile = path.resolve(__dirname, '../../../app/api/auth', route, 'route.ts');
      expect(existsSync(routeFile)).toBe(false);
    }
  );

  it.each(['enterprise', 'pro', 'free'])(
    'sends only the ID token and user agent to the API even when the client asks for "%s"',
    async (requestedPlan) => {
      // An attacker can still POST extra arguments to the server action; they must be ignored.
      const verifyTokenAction = authActions.verifyTokenAction as unknown as (
        idToken: string,
        metadata?: { selectedPlan?: string }
      ) => Promise<unknown>;

      await verifyTokenAction('id-token', { selectedPlan: requestedPlan });

      expect(mocks.createBackendSession).toHaveBeenCalledTimes(1);
      expect(mocks.createBackendSession).toHaveBeenCalledWith('id-token', 'vitest');
    }
  );

  describe('KAN-41: explicit sign-in goes through the API', () => {
    it('sets the backend-issued httpOnly session cookie and reports the verified-email claim', async () => {
      const result = await authActions.verifyTokenAction('id-token');

      expect(result).toEqual({ success: true, data: { claimsEmailVerified: false } });
      expect(mocks.cookieSet).toHaveBeenCalledWith(
        'session',
        'backend-session-cookie',
        expect.objectContaining({ httpOnly: true, sameSite: 'lax', path: '/', maxAge: 432000 })
      );
    });

    it.each([401, 409, 429])(
      'returns the generic error and sets no cookie when the API answers %s',
      async (status) => {
        mocks.createBackendSession.mockResolvedValue({
          success: false,
          error: 'Account conflict',
          status,
        });

        const result = await authActions.verifyTokenAction('id-token');

        expect(result).toEqual({ success: false, error: 'Token verification failed' });
        expect(mocks.cookieSet).not.toHaveBeenCalled();
      }
    );

    // KAN-240: an outage is reported as such, not as a bad token.
    it.each([503, undefined])(
      'reports the service as unavailable and sets no cookie when the API answers %s',
      async (status) => {
        mocks.createBackendSession.mockResolvedValue({
          success: false,
          error: 'Backend unavailable',
          status,
        });

        const result = await authActions.verifyTokenAction('id-token');

        expect(result).toEqual({ success: false, error: SIGN_IN_SERVICE_UNAVAILABLE_ERROR });
        expect(mocks.cookieSet).not.toHaveBeenCalled();
      }
    );
  });

  describe('KAN-163: a session refresh records no login (no API sign-in)', () => {
    beforeEach(() => {
      mocks.verifyBackendIdToken.mockResolvedValue(idTokenOk(true));
    });

    it('refreshes through the API (KAN-183) with a matching session: no sign-in API', async () => {
      mocks.cookieGet.mockReturnValue({ value: 'old-session' });
      mocks.fetchSessionStatus.mockResolvedValue(sessionOk('uid-1'));
      const result = await authActions.refreshSessionAction('id-token');

      expect(result.success).toBe(true);
      expect(result.data.claimsEmailVerified).toBe(true);
      expect(mocks.refreshBackendSession).toHaveBeenCalledWith('id-token');
      expect(mocks.createBackendSession).not.toHaveBeenCalled();
      expect(mocks.cookieSet).toHaveBeenCalledWith(
        'session',
        'refreshed-session-cookie',
        expect.objectContaining({ httpOnly: true, maxAge: 432000 })
      );
    });

    describe('KAN-183: a rejected refresh sends the user to sign in again', () => {
      beforeEach(() => {
        mocks.cookieGet.mockReturnValue({ value: 'old-session' });
        mocks.fetchSessionStatus.mockResolvedValue(sessionOk('uid-1'));
      });

      it.each([401, 403, 409, 422])(
        'clears the session and asks for sign-in when the API answers %s (e.g. ID token too old)',
        async (status) => {
          mocks.refreshBackendSession.mockResolvedValue({
            success: false,
            error: 'Invalid authentication',
            status,
          });

          const result = await authActions.refreshSessionAction('id-token');

          expect(result).toEqual({
            success: false,
            error: 'Token verification failed',
            data: { signInRequired: true },
          });
          expect(mocks.cookieDelete).toHaveBeenCalledWith('session');
          expect(mocks.cookieSet).not.toHaveBeenCalled();
        }
      );

      it.each([
        [429, 'Token verification failed'],
        [503, SIGN_IN_SERVICE_UNAVAILABLE_ERROR],
        [undefined, SIGN_IN_SERVICE_UNAVAILABLE_ERROR],
      ])(
        'fails without ending the session when the API answers %s',
        async (status, expectedError) => {
          mocks.refreshBackendSession.mockResolvedValue({
            success: false,
            error: 'Backend unavailable',
            status,
          });

          const result = await authActions.refreshSessionAction('id-token');

          expect(result).toEqual({ success: false, error: expectedError });
          expect(mocks.cookieDelete).not.toHaveBeenCalled();
          expect(mocks.cookieSet).not.toHaveBeenCalled();
        }
      );
    });

    it('checks the existing session through the backend status (revocation) and does not require email_verified', async () => {
      mocks.verifyBackendIdToken.mockResolvedValue(idTokenOk(false));
      mocks.cookieGet.mockReturnValue({ value: 'old-session' });
      mocks.fetchSessionStatus.mockResolvedValue({
        success: true,
        data: { uid: 'uid-1', email: 'new@example.com', email_verified: false },
      });

      await authActions.refreshSessionAction('id-token');

      expect(mocks.fetchSessionStatus).toHaveBeenCalledTimes(1);
      expect(mocks.refreshBackendSession).toHaveBeenCalledWith('id-token');
      expect(mocks.createBackendSession).not.toHaveBeenCalled();
    });

    it('signs in through the API once when refresh has no existing session', async () => {
      await authActions.refreshSessionAction('id-token');

      expect(mocks.createBackendSession).toHaveBeenCalledTimes(1);
    });

    it('signs in through the API once when the existing session belongs to another user', async () => {
      mocks.cookieGet.mockReturnValue({ value: 'other-session' });
      mocks.fetchSessionStatus.mockResolvedValue(sessionOk('uid-2'));

      await authActions.refreshSessionAction('id-token');

      expect(mocks.createBackendSession).toHaveBeenCalledTimes(1);
    });

    it('treats refresh with a revoked existing session (401 Invalid authentication) as an explicit sign-in', async () => {
      mocks.cookieGet.mockReturnValue({ value: 'revoked-session' });
      mocks.fetchSessionStatus.mockResolvedValue(REVOKED_SESSION);

      await authActions.refreshSessionAction('id-token');

      expect(mocks.createBackendSession).toHaveBeenCalledTimes(1);
      expect(mocks.refreshBackendSession).not.toHaveBeenCalled();
    });

    it('also signs in explicitly when the session status check is down (the session cannot be proven active)', async () => {
      mocks.cookieGet.mockReturnValue({ value: 'old-session' });
      mocks.fetchSessionStatus.mockResolvedValue({ success: false, error: 'Backend unavailable' });

      await authActions.refreshSessionAction('id-token');

      expect(mocks.createBackendSession).toHaveBeenCalledTimes(1);
      expect(mocks.refreshBackendSession).not.toHaveBeenCalled();
    });

    it('still rejects an invalid token on refresh without calling the API', async () => {
      mocks.verifyBackendIdToken.mockResolvedValue({
        success: false,
        error: 'Invalid authentication',
        status: 401,
      });

      const result = await authActions.refreshSessionAction('bad');

      expect(result.success).toBe(false);
      expect(mocks.createBackendSession).not.toHaveBeenCalled();
      expect(mocks.refreshBackendSession).not.toHaveBeenCalled();
    });
  });

  describe('KAN-168: revoked ID tokens are rejected at sign-in and refresh', () => {
    beforeEach(() => {
      // The backend verifies with revocation checking and answers 401 for a revoked ID token.
      mocks.verifyBackendIdToken.mockResolvedValue({
        success: false,
        error: 'The Firebase ID token has been revoked.',
        status: 401,
      });
    });

    it.each(['verifyTokenAction', 'refreshSessionAction'] as const)(
      '%s checks revocation, returns the generic error, sets no cookie and does not call the API',
      async (action) => {
        const result = await authActions[action]('revoked-token');

        expect(mocks.verifyBackendIdToken).toHaveBeenCalledWith('revoked-token');
        expect(result).toEqual({ success: false, error: 'Token verification failed' });
        expect(JSON.stringify(result)).not.toContain('revoked');
        expect(mocks.cookieSet).not.toHaveBeenCalled();
        expect(mocks.createBackendSession).not.toHaveBeenCalled();
      }
    );

    it('verifies a good ID token through the backend on sign-in too', async () => {
      mocks.verifyBackendIdToken.mockResolvedValue(idTokenOk(true));

      const result = await authActions.verifyTokenAction('good-token');

      expect(result.success).toBe(true);
      expect(mocks.verifyBackendIdToken).toHaveBeenCalledWith('good-token');
    });
  });
});
