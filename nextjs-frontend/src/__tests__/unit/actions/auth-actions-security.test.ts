// @vitest-environment node
/**
 * Regression tests for KAN-122: auth server actions must not allow account takeover or plan escalation.
 */
import { existsSync } from 'node:fs';
import path from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  verifyIdToken: vi.fn(),
  getUser: vi.fn(),
  userFindUnique: vi.fn(),
  userCreate: vi.fn(),
  userUpdate: vi.fn(),
  historyFindFirst: vi.fn(),
  historyCreate: vi.fn(),
  notifyNewDeviceLogin: vi.fn(),
  createSessionCookie: vi.fn(),
  verifySessionCookie: vi.fn(),
  cookieGet: vi.fn(),
  cookieSet: vi.fn(),
}));

vi.mock('next/headers', () => ({
  headers: async () => new Headers({ 'user-agent': 'vitest' }),
  cookies: async () => ({ set: mocks.cookieSet, get: mocks.cookieGet, delete: vi.fn() }),
}));
vi.mock('@/lib/firebase/admin', () => ({
  getAdminAuth: () => ({
    verifyIdToken: mocks.verifyIdToken,
    getUser: mocks.getUser,
    createSessionCookie: mocks.createSessionCookie,
    verifySessionCookie: mocks.verifySessionCookie,
  }),
}));
vi.mock('@/lib/firebase/client', () => ({ auth: {} }));
vi.mock('firebase/auth', () => ({ applyActionCode: vi.fn() }));
vi.mock('@/lib/db/client', () => ({
  db: {
    user: { findUnique: mocks.userFindUnique, create: mocks.userCreate, update: mocks.userUpdate },
    userSettings: { create: vi.fn() },
    loginHistory: { findFirst: mocks.historyFindFirst, create: mocks.historyCreate },
  },
}));
vi.mock('@/lib/utils/geo-ip', () => ({ getLocationFromIP: vi.fn().mockResolvedValue(null) }));
vi.mock('@/lib/utils/notifications', () => ({
  notifyNewDeviceLogin: mocks.notifyNewDeviceLogin,
  notifyEmailVerified: vi.fn(),
}));
vi.mock('@/lib/logger', () => ({ logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() } }));

import * as authActions from '@/app/actions/auth-actions';

describe('KAN-122: auth server actions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.verifyIdToken.mockResolvedValue({
      uid: 'uid-1',
      email: 'new@example.com',
      email_verified: false,
    });
    mocks.getUser.mockResolvedValue({
      uid: 'uid-1',
      displayName: null,
      photoURL: null,
      phoneNumber: null,
    });
    mocks.userFindUnique.mockResolvedValue(null);
    mocks.userCreate.mockResolvedValue({
      id: 'user-1',
      email: 'new@example.com',
      subscriptionTier: 'free',
    });
    mocks.historyFindFirst.mockResolvedValue(null);
    mocks.createSessionCookie.mockResolvedValue('session-cookie');
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
    'creates a new user on the free tier even when the client asks for "%s"',
    async (requestedPlan) => {
      // An attacker can still POST extra arguments to the server action; they must be ignored.
      const verifyTokenAction = authActions.verifyTokenAction as unknown as (
        idToken: string,
        metadata?: { selectedPlan?: string }
      ) => Promise<unknown>;

      await verifyTokenAction('id-token', { selectedPlan: requestedPlan });

      expect(mocks.userCreate).toHaveBeenCalledTimes(1);
      expect(mocks.userCreate.mock.calls[0][0].data.subscriptionTier).toBe('free');
    }
  );

  describe('KAN-163: login history is recorded only for explicit sign-ins', () => {
    const existingUser = {
      id: 'user-1',
      email: 'new@example.com',
      emailVerified: true,
      subscriptionTier: 'free',
    };

    beforeEach(() => {
      mocks.verifyIdToken.mockResolvedValue({
        uid: 'uid-1',
        email: 'new@example.com',
        email_verified: true,
      });
      mocks.userFindUnique.mockResolvedValue(existingUser);
    });

    it('records exactly one history row and the new-device notice for an explicit sign-in', async () => {
      const result = await authActions.verifyTokenAction('id-token');

      expect(result.success).toBe(true);
      expect(mocks.historyCreate).toHaveBeenCalledTimes(1);
      expect(mocks.historyCreate.mock.calls[0][0].data).toMatchObject({
        userId: 'user-1',
        successful: true,
      });
      expect(mocks.notifyNewDeviceLogin).toHaveBeenCalledTimes(1);
      expect(mocks.userUpdate.mock.calls[0][0].data.lastLoginAt).toBeInstanceOf(Date);
    });

    it('records no history and sends no notice on session refresh, but still mints the cookie', async () => {
      mocks.cookieGet.mockReturnValue({ value: 'old-session' });
      mocks.verifySessionCookie.mockResolvedValue({ uid: 'uid-1' });
      const result = await authActions.refreshSessionAction('id-token');

      expect(result.success).toBe(true);
      expect(result.data.claimsEmailVerified).toBe(true);
      expect(mocks.createSessionCookie).toHaveBeenCalledWith('id-token', expect.any(Object));
      expect(mocks.historyCreate).not.toHaveBeenCalled();
      expect(mocks.historyFindFirst).not.toHaveBeenCalled();
      expect(mocks.notifyNewDeviceLogin).not.toHaveBeenCalled();
      expect(mocks.userUpdate.mock.calls[0][0].data).not.toHaveProperty('lastLoginAt');
    });

    it('verifies the existing session with revocation checking and does not require email_verified', async () => {
      mocks.verifyIdToken.mockResolvedValue({
        uid: 'uid-1',
        email: 'new@example.com',
        email_verified: false,
      });
      mocks.cookieGet.mockReturnValue({ value: 'old-session' });
      mocks.verifySessionCookie.mockResolvedValue({ uid: 'uid-1' });

      await authActions.refreshSessionAction('id-token');

      expect(mocks.verifySessionCookie).toHaveBeenCalledWith('old-session', true);
      expect(mocks.historyCreate).not.toHaveBeenCalled();
    });

    it('records once like a sign-in when refresh has no existing session', async () => {
      await authActions.refreshSessionAction('id-token');

      expect(mocks.historyCreate).toHaveBeenCalledTimes(1);
      expect(mocks.notifyNewDeviceLogin).toHaveBeenCalledTimes(1);
    });

    it('records once when the existing session belongs to another user', async () => {
      mocks.cookieGet.mockReturnValue({ value: 'other-session' });
      mocks.verifySessionCookie.mockResolvedValue({ uid: 'uid-2' });

      await authActions.refreshSessionAction('id-token');

      expect(mocks.historyCreate).toHaveBeenCalledTimes(1);
    });

    it('records once when the existing session is revoked or invalid', async () => {
      mocks.cookieGet.mockReturnValue({ value: 'revoked-session' });
      mocks.verifySessionCookie.mockRejectedValue(new Error('auth/session-cookie-revoked'));

      await authActions.refreshSessionAction('id-token');

      expect(mocks.historyCreate).toHaveBeenCalledTimes(1);
    });

    it('still rejects an invalid token on refresh without recording anything', async () => {
      mocks.verifyIdToken.mockRejectedValue(new Error('bad token'));

      const result = await authActions.refreshSessionAction('bad');

      expect(result.success).toBe(false);
      expect(mocks.createSessionCookie).not.toHaveBeenCalled();
      expect(mocks.historyCreate).not.toHaveBeenCalled();
    });
  });

  describe('KAN-168: revoked ID tokens are rejected at sign-in and refresh', () => {
    const revokedError = Object.assign(new Error('The Firebase ID token has been revoked.'), {
      code: 'auth/id-token-revoked',
    });

    beforeEach(() => {
      mocks.verifyIdToken.mockRejectedValue(revokedError);
    });

    it.each(['verifyTokenAction', 'refreshSessionAction'] as const)(
      '%s checks revocation, returns the generic error, sets no cookie and records no history',
      async (action) => {
        const result = await authActions[action]('revoked-token');

        expect(mocks.verifyIdToken).toHaveBeenCalledWith('revoked-token', true);
        expect(result).toEqual({ success: false, error: 'Token verification failed' });
        expect(JSON.stringify(result)).not.toContain('revoked');
        expect(mocks.createSessionCookie).not.toHaveBeenCalled();
        expect(mocks.cookieSet).not.toHaveBeenCalled();
        expect(mocks.historyCreate).not.toHaveBeenCalled();
        expect(mocks.userCreate).not.toHaveBeenCalled();
        expect(mocks.userUpdate).not.toHaveBeenCalled();
        expect(mocks.notifyNewDeviceLogin).not.toHaveBeenCalled();
      }
    );

    it('passes checkRevoked=true on a successful sign-in too', async () => {
      mocks.verifyIdToken.mockResolvedValue({
        uid: 'uid-1',
        email: 'new@example.com',
        email_verified: true,
      });

      const result = await authActions.verifyTokenAction('good-token');

      expect(result.success).toBe(true);
      expect(mocks.verifyIdToken).toHaveBeenCalledWith('good-token', true);
    });
  });
});
